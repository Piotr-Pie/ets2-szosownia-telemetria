#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - klient telemetrii, okno .exe (v0.2.0)
========================================================

Okno tkinter (stdlib, bez zadnych zewnetrznych zaleznosci GUI - wymagane
przez zlecenie: jeden plik .exe, bez cmd, bez Pythona widocznego dla
gracza, bez edycji config.json recznie).

Caly ekran:
  - pole tokena (maskowane, show="*")
  - przycisk "Zapisz i uruchom"
  - przycisk "Wybierz folder gry..." (filedialog, uzywany gdy automatyczne
    wyszukiwanie w core.game_finder nie znajdzie gry)
  - pole statusu (ta sama trosc co linie [status] z CLI v0.1.3, patrz
    core.ets2_core.status_line / mem_error_status_line)
  - przycisk "Zatrzymaj"
Zamkniecie okna (X) zatrzymuje wysylke (WM_DELETE_WINDOW -> stop_event).

Token NIGDY nie jest wypisywany: nie w tytule okna, nie w polu statusu,
nie w zadnym logu/wyjatku propagowanym do GUI - wszystkie komunikaty
budowane tutaj sa STALYMI tekstami albo zawieraja wylacznie: sciezke
pliku, kod bledu HTTP, tresc wyjatku sieciowego (ApiError nie ma dostepu
do tokena - patrz core/ets2_core.py TelemetrySender.send()).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config_store, game_finder, plugin_installer
from core.ets2_core import (
    BUFFER_WINDOW_S,
    CLIENT_NAME,
    CLIENT_VERSION,
    SERVER_URL,
    SEND_INTERVAL_CONNECTED,
    SEND_INTERVAL_DISCONNECTED,
    ApiError,
    CertPinMismatchError,
    EventTracker,
    FatalAuthError,
    SharedMemoryReader,
    TelemetrySender,
    build_packet,
    is_game_process_running,
    mem_error_status_line,
    safe_parse_telemetry,
    safe_read_memory,
    status_line,
)

WINDOW_TITLE = f"ETS2 Szosownia - klient telemetrii v{CLIENT_VERSION}"
TOKEN_REJECTED_MSG = "Token odrzucony — wygeneruj nowy na szosownia.com/konto"


def plugin_installed_message(path: str) -> str:
    return f"Plugin zainstalowany w: {path}"


class TelemetryWorker:
    """Petla wysylkowa (2 Hz) dzialajaca w osobnym wątku, zeby nie blokowac
    tkinter mainloop. Logika identyczna z main() z client/client.py
    (v0.1.3) - buforowanie 60s, backoff na 429, stop na 401/pin mismatch -
    tylko print() zastapiony wywolaniem on_status(tekst) do GUI."""

    def __init__(self, token: str, tls_sha256_pin: str | None, on_status):
        self._sender = TelemetrySender(SERVER_URL, token, tls_sha256_pin)
        self._reader = SharedMemoryReader()
        self._tracker = EventTracker()
        self._on_status = on_status
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        buffer: deque = deque()
        last_state = None
        last_mem_error = None
        self._on_status(f"{CLIENT_NAME} v{CLIENT_VERSION} - start (serwer: {SERVER_URL})")

        while not self._stop_event.is_set():
            raw, mem_err = safe_read_memory(self._reader)
            parsed = None
            events: list[dict] = []

            if mem_err is None and raw is not None:
                parsed, mem_err = safe_parse_telemetry(raw)
                if mem_err is not None:
                    raw = None

            if mem_err is not None:
                if mem_err != last_mem_error:
                    last_mem_error = mem_err
                    self._on_status(mem_error_status_line(mem_err))
            else:
                last_mem_error = None

            connected = raw is not None and parsed is not None
            running = is_game_process_running() or connected

            if connected:
                ev = self._tracker.check(parsed)
                if ev:
                    events.append(ev)

            state = (running, connected)
            if state != last_state:
                last_state = state
                self._on_status(status_line(running, connected))

            packet = build_packet(connected, running, parsed, events)
            now = time.monotonic()
            buffer.append((now, packet))
            while buffer and (now - buffer[0][0]) > BUFFER_WINDOW_S:
                buffer.popleft()

            stopped = False
            while buffer:
                _, pkt = buffer[0]
                try:
                    self._sender.send(pkt)
                    buffer.popleft()
                except FatalAuthError:
                    self._on_status(TOKEN_REJECTED_MSG)
                    stopped = True
                    break
                except CertPinMismatchError as e:
                    self._on_status(f"[BŁĄD] {e}")
                    stopped = True
                    break
                except ApiError as e:
                    msg = str(e)
                    if "HTTP 400" in msg or "HTTP 413" in msg:
                        buffer.popleft()
                        continue
                    if "HTTP 429" in msg:
                        self._on_status("[info] limit 429, czekam (backoff)")
                        self._sender.backoff_sleep()
                        break
                    self._on_status(f"[info] brak sieci / błąd serwera ({msg}), buforuję")
                    break

            if stopped:
                self._stop_event.set()
                break

            interval = SEND_INTERVAL_CONNECTED if connected else SEND_INTERVAL_DISCONNECTED
            self._stop_event.wait(interval)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.worker: TelemetryWorker | None = None
        self.game_root: str | None = None

        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Token konta (szosownia.com/konto):").grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        self.token_var = tk.StringVar()
        self.token_entry = ttk.Entry(frm, textvariable=self.token_var, show="*", width=42)
        self.token_entry.grid(row=1, column=0, columnspan=2, sticky="we", **pad)

        self.game_root_var = tk.StringVar(value="(szukam automatycznie...)")
        ttk.Label(frm, textvariable=self.game_root_var, foreground="#555").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10
        )

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=3, column=0, columnspan=2, sticky="we", **pad)
        self.save_btn = ttk.Button(btn_frame, text="Zapisz i uruchom", command=self.on_save_and_start)
        self.save_btn.pack(side="left", padx=(0, 6))
        self.choose_btn = ttk.Button(btn_frame, text="Wybierz folder gry…", command=self.on_choose_folder)
        self.choose_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btn_frame, text="Zatrzymaj", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left")

        ttk.Separator(frm).grid(row=4, column=0, columnspan=2, sticky="we", padx=10, pady=4)

        ttk.Label(frm, text="Status:").grid(row=5, column=0, columnspan=2, sticky="w", padx=10)
        self.status_var = tk.StringVar(value="Gotowy. Wklej token i kliknij „Zapisz i uruchom”.")
        self.status_label = ttk.Label(
            frm, textvariable=self.status_var, wraplength=380, foreground="#222"
        )
        self.status_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._load_existing_config()
        self._auto_find_game()

    # -- pomocnicze -------------------------------------------------------

    def set_status(self, text: str):
        """Wolane z wątku roboczego - Tkinter nie jest thread-safe, wiec
        marshalling przez root.after(0, ...)."""
        self.root.after(0, lambda: self.status_var.set(text))

    def _load_existing_config(self):
        cfg = config_store.load_config()
        if cfg:
            self.token_var.set(cfg["token"])
            self.status_var.set("Wczytano zapisany token z poprzedniej konfiguracji.")

    def _auto_find_game(self):
        root, checked = game_finder.find_game_root()
        if root:
            self.game_root = root
            self.game_root_var.set(f"Gra znaleziona: {root}")
        else:
            self.game_root_var.set(
                "Nie znalazłem gry automatycznie — kliknij „Wybierz folder gry…”."
            )

    # -- obsluga przyciskow ------------------------------------------------

    def on_choose_folder(self):
        selected = filedialog.askdirectory(title="Wybierz folder Euro Truck Simulator 2")
        if not selected:
            return
        normalized = game_finder.normalize_game_path_input(selected)
        root = game_finder.is_valid_game_root(normalized)
        if not root:
            messagebox.showerror(
                "Nie znaleziono gry",
                "W wybranym folderze nie ma pliku bin\\win_x64\\eurotrucks2.exe.\n"
                "Wybierz główny folder Euro Truck Simulator 2.",
            )
            return
        self.game_root = root
        self.game_root_var.set(f"Gra znaleziona: {root}")

    def on_save_and_start(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Brak tokena", "Wklej token z panelu konta na szosownia.com.")
            return
        if not self.game_root:
            messagebox.showerror(
                "Nie znaleziono gry",
                "Najpierw wybierz folder Euro Truck Simulator 2 (przycisk "
                "„Wybierz folder gry…”).",
            )
            return

        try:
            path = plugin_installer.install_plugin(self.game_root)
        except plugin_installer.PluginInstallError as e:
            messagebox.showerror("Błąd instalacji pluginu", str(e))
            return
        self.status_var.set(plugin_installed_message(path))

        try:
            config_store.save_config(token)
        except (OSError, ValueError) as e:
            messagebox.showerror("Błąd zapisu konfiguracji", str(e))
            return

        self.save_btn.config(state="disabled")
        self.choose_btn.config(state="disabled")
        self.token_entry.config(state="disabled")
        self.stop_btn.config(state="normal")

        self.worker = TelemetryWorker(token, None, self.set_status)
        self.worker.start()

    def on_stop(self):
        if self.worker:
            self.worker.stop()
        self.save_btn.config(state="normal")
        self.choose_btn.config(state="normal")
        self.token_entry.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Zatrzymano przez użytkownika.")

    def on_close(self):
        if self.worker:
            self.worker.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
