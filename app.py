#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - klient telemetrii, okno .exe (v0.2.2)
========================================================

Okno tkinter (stdlib, bez zadnych zewnetrznych zaleznosci GUI - wymagane
przez zlecenie: jeden plik .exe, bez cmd, bez Pythona widocznego dla
gracza, bez edycji config.json recznie).

Caly ekran:
  - pole tokena (maskowane, show="*")
  - przycisk "Zapisz i uruchom"
  - przycisk "Wybierz folder gry..." (filedialog, uzywany gdy automatyczne
    wyszukiwanie w core.game_finder nie znajdzie gry)
  - checkbox "Uruchamiaj razem z Windows" (DOMYSLNIE WYLACZONY, v0.2.2)
  - przycisk "Utworz skrot na pulpicie" (v0.2.2)
  - pole statusu (ta sama trosc co linie [status] z CLI v0.1.3, patrz
    core.ets2_core.status_line / mem_error_status_line) - ten sam tekst
    jest tooltipem ikony zasobnika, gdy zasobnik dziala (v0.2.2)
  - przycisk "Zatrzymaj"

NOWOSCI v0.2.2 (zlecenie koordynatora - ikona zasobnika, autostart,
skrot na pulpicie, pojedyncza instancja):
  - Zasobnik systemowy (pystray + Pillow, core/tray_icon.py): klik ->
    pokaz okno; menu "Pokaz okno" / "Wstrzymaj wysylke lub Wznow" /
    "Zakoncz". Import pystray jest w szerokim try/except (NIE tylko
    ImportError) - na Linuksie bez serwera X pystray rzuca
    Xlib.error.DisplayNameError przy samym imporcie (zweryfikowane w tej
    sesji, patrz tests/test_tray_icon.py i raport) - program dziala dalej
    jako zwykle okno, gdy zasobnik sie nie uruchomi.
  - Zamkniecie okna (X) chowa do zasobnika (NIE koczy programu), jesli
    zasobnik dziala; gdy zasobnik niedostepny - X zamyka program jak w
    v0.2.1 (logika w core/window_controller.py, testowalna na atrapie
    okna).
  - Autostart z Windows (core/autostart.py, winreg, Windows-only) -
    checkbox zapisuje/usuwa wpis w HKCU Run, wartosc: sciezka do exe w
    cudzyslowach + flaga --tray.
  - Skrot na pulpicie (core/shortcut.py, PowerShell przez subprocess,
    sciezki przekazane WYLACZNIE przez zmienne srodowiskowe - bez
    wstrzykiwania).
  - Pojedyncza instancja (core/single_instance.py, named mutex
    "ETS2SzosowniaTelemetria") - druga instancja przywoluje okno
    pierwszej i sie zamyka, patrz main().
  - Start z flaga --tray: okno startuje zminimalizowane do zasobnika; gdy
    jest juz zapisana konfiguracja (token) i znaleziona gra, wysylka
    startuje automatycznie bez klikania "Zapisz i uruchom" (UWAGA: to
    oznacza, ze przy autostarcie z Windows klient wysyla heartbeat (co 5
    s, game.running=false) CALY CZAS od zalogowania do Windows, nawet gdy
    gracz nie planuje grac w ten dzien - decyzja do potwierdzenia przez
    wlasciciela, patrz raport).

Zamkniecie okna (X) zatrzymuje wysylke (WM_DELETE_WINDOW -> stop_event)
TYLKO gdy zasobnik jest niedostepny - patrz wyzej.

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

from core import (
    autostart,
    config_store,
    game_finder,
    plugin_installer,
    shortcut,
    single_instance,
    window_controller,
)
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
from core.tray_icon import build_icon_image

# Import pystray jest w SZEROKIM except (nie tylko ImportError) - na
# Linuksie bez serwera X pystray rzuca Xlib.error.DisplayNameError juz
# przy samym imporcie (zweryfikowane w tej sesji, patrz raport i
# tests/test_tray_icon.py). Na Windows (produkcja) backend to win32 i ten
# problem nie wystepuje.
try:
    import pystray
    TRAY_IMPORT_ERROR: Exception | None = None
except Exception as _e:  # noqa: BLE001 - patrz docstring powyzej
    pystray = None  # type: ignore[assignment]
    TRAY_IMPORT_ERROR = _e

TRAY_AVAILABLE = pystray is not None

WINDOW_TITLE = f"ETS2 Szosownia - klient telemetrii v{CLIENT_VERSION}"
TOKEN_REJECTED_MSG = "Token odrzucony — wygeneruj nowy na szosownia.com/konto"
TRAY_FLAG = "--tray"


def plugin_installed_message(path: str) -> str:
    return f"Plugin zainstalowany w: {path}"


def get_exe_path() -> str:
    """Pelna sciezka do uruchomionego .exe (frozen - PyInstaller) albo do
    tego pliku .py (dev). Uzywane przez autostart (wpis rejestru) i skrot
    na pulpicie (TargetPath)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)


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
    def __init__(self, root: tk.Tk, start_hidden: bool = False):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.worker: TelemetryWorker | None = None
        self.game_root: str | None = None
        self.tray_icon = None
        self._sending_paused = False

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

        # -- v0.2.2: autostart + skrot na pulpicie ------------------------
        extras_frame = ttk.Frame(frm)
        extras_frame.grid(row=4, column=0, columnspan=2, sticky="we", **pad)
        self.autostart_var = tk.BooleanVar(value=False)
        try:
            self.autostart_var.set(autostart.is_autostart_enabled())
        except Exception:  # noqa: BLE001 - checkbox po prostu zostaje wylaczony
            pass
        self.autostart_chk = ttk.Checkbutton(
            extras_frame,
            text="Uruchamiaj razem z Windows",
            variable=self.autostart_var,
            command=self.on_toggle_autostart,
        )
        self.autostart_chk.pack(side="left", padx=(0, 10))
        self.shortcut_btn = ttk.Button(
            extras_frame, text="Utwórz skrót na pulpicie", command=self.on_create_shortcut
        )
        self.shortcut_btn.pack(side="left")

        ttk.Separator(frm).grid(row=5, column=0, columnspan=2, sticky="we", padx=10, pady=4)

        ttk.Label(frm, text="Status:").grid(row=6, column=0, columnspan=2, sticky="w", padx=10)
        self.status_var = tk.StringVar(value="Gotowy. Wklej token i kliknij „Zapisz i uruchom”.")
        self.status_label = ttk.Label(
            frm, textvariable=self.status_var, wraplength=380, foreground="#222"
        )
        self.status_label.grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))

        self.tray_controller = window_controller.TrayWindowController(
            self.root, tray_available=TRAY_AVAILABLE, on_stop_sending=self._stop_sending_for_quit
        )
        self.root.protocol("WM_DELETE_WINDOW", self.tray_controller.on_window_close_button)

        if TRAY_AVAILABLE:
            self._setup_tray_icon()

        self._load_existing_config()
        self._auto_find_game()

        if start_hidden:
            self.root.withdraw()
            self.tray_controller.visible = False
            if config_store.load_config() is not None and self.game_root:
                self.on_save_and_start()

    # -- zasobnik (pystray) -------------------------------------------------

    def _setup_tray_icon(self):
        """Buduje i startuje ikone zasobnika w osobnym wątku (daemon).
        Kazdy blad (np. brak serwera X na Linuksie) jest chwytany - program
        dziala dalej jako zwykle okno (patrz TRAY_AVAILABLE/docstring)."""
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Pokaż okno", self._on_tray_show, default=True),
                pystray.MenuItem(self._tray_pause_label, self._on_tray_toggle_pause),
                pystray.MenuItem("Zakończ", self._on_tray_quit),
            )
            self.tray_icon = pystray.Icon(
                "ets2szosownia", build_icon_image(), self.status_var.get(), menu=menu
            )
            self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self._tray_thread.start()
        except Exception:  # noqa: BLE001
            self.tray_icon = None
            self.tray_controller.tray_available = False

    def _tray_pause_label(self, item) -> str:
        return "Wznów wysyłkę" if self._sending_paused else "Wstrzymaj wysyłkę"

    def _on_tray_show(self, icon, item):
        self.root.after(0, self.tray_controller.show)

    def _on_tray_toggle_pause(self, icon, item):
        self.root.after(0, self._handle_tray_pause_toggle)

    def _handle_tray_pause_toggle(self):
        if self._sending_paused:
            self.on_save_and_start()
        else:
            self.on_stop()

    def _on_tray_quit(self, icon, item):
        icon.stop()
        self.root.after(0, self.tray_controller.quit)

    def _stop_sending_for_quit(self):
        if self.worker:
            self.worker.stop()

    # -- pomocnicze -------------------------------------------------------

    def set_status(self, text: str):
        """Wolane z wątku roboczego - Tkinter nie jest thread-safe, wiec
        marshalling przez root.after(0, ...). Ten sam tekst trafia do
        tooltipa ikony zasobnika (v0.2.2), jesli zasobnik dziala."""
        self.root.after(0, lambda: self._apply_status(text))

    def _apply_status(self, text: str):
        self.status_var.set(text)
        if self.tray_icon is not None:
            try:
                self.tray_icon.title = text[:127]  # limit tooltipa Windows
            except Exception:  # noqa: BLE001
                pass

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
        self._sending_paused = False

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
        self._sending_paused = True

    def on_toggle_autostart(self):
        """Checkbox 'Uruchamiaj razem z Windows' - zapisuje/usuwa wpis w
        HKCU Run (core/autostart.py). Blad (np. brak dostepu do rejestru)
        pokazuje komunikat i przywraca checkbox do stanu przed klikiem."""
        enabled = self.autostart_var.get()
        exe_path = get_exe_path()
        try:
            if enabled:
                autostart.enable_autostart(exe_path)
            else:
                autostart.disable_autostart()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Błąd autostartu", f"Nie udało się zmienić wpisu autostartu: {e}"
            )
            self.autostart_var.set(not enabled)

    def on_create_shortcut(self):
        """Przycisk 'Utwórz skrót na pulpicie' (core/shortcut.py,
        PowerShell przez subprocess, sciezki tylko przez zmienne
        srodowiskowe - bez wstrzykiwania)."""
        exe_path = get_exe_path()
        try:
            path = shortcut.create_desktop_shortcut(exe_path)
        except shortcut.ShortcutError as e:
            messagebox.showerror("Błąd tworzenia skrótu", str(e))
            return
        messagebox.showinfo("Skrót utworzony", f"Skrót utworzony: {path}")


def main():
    tray_flag = TRAY_FLAG in sys.argv[1:]

    guard = single_instance.SingleInstanceGuard()
    if not guard.acquire():
        # Druga instancja: przywolaj okno pierwszej i zakoncz sie, zamiast
        # tworzyc drugiego klienta (patrz core/single_instance.py).
        single_instance.try_focus_existing_window(WINDOW_TITLE)
        return

    try:
        root = tk.Tk()
        App(root, start_hidden=tray_flag)
        root.mainloop()
    finally:
        guard.release()


if __name__ == "__main__":
    main()
