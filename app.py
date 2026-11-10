#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - klient telemetrii, okno .exe (v0.2.6)
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
  - checkbox "Wysyłaj tylko gdy gra działa" (DOMYSLNIE WLACZONY, v0.2.6)
  - przycisk "Utworz skrot na pulpicie" (v0.2.2)
  - pole statusu (diagnostyka szczegolowa - [status] gra dziala/pamiec
    SCS itd., core.ets2_core.status_line/mem_error_status_line)
  - przycisk "Zatrzymaj"

NOWOSCI v0.2.6 (kontrakt v5, docs/telemetry-contract-v5.md - zlecenie
koordynatora z 2026-11-10, naprawa bledu zgloszonego przez wlasciciela):
  BLAD NAPRAWIONY: w v0.2.3-0.2.5 "Wstrzymaj wysyłkę" z menu zasobnika
  NIE gwarantowalo zera pakietow - szczegolowa przyczyna (nazwa funkcji,
  linia) w core/telemetry_worker.py (docstring modulu) i w raporcie
  workspace/client-exe-v0.2.6.md. Skrot: stary TelemetryWorker.stop()
  tylko ustawial `threading.Event`, sprawdzany jedynie na poczatku
  petli `while` - w trakcie drenazu bufora/backoff_sleep() watek
  dokanczal wysylke mimo klikniecia pauzy, a kazde "Wznow" tworzylo
  NOWY watek bez czekania na koniec poprzedniego (mozliwe "zombie"
  watki wysylajace w tle).

  NAPRAWA: cala logika gatingu (manual pause / auto pause / baseline)
  wydzielona do core/telemetry_worker.py (TelemetryWorker, NOWY MODUL,
  testowalny bez tkinter - patrz tests/test_telemetry_worker.py). Jeden
  dlugozyjacy watek na cale zycie aplikacji; pauza/wznowienie TYLKO
  przelacza flagi sprawdzane na samym poczatku kazdego ticku - PRZED
  jakimkolwiek odczytem pamieci/wyslaniem. Bufor jest czyszczony przy
  KAZDYM wejsciu w stan wstrzymany.

  NOWA OPCJA "Wysyłaj tylko gdy gra działa" (domyslnie WLACZONA, zapisywana
  w config.json jako game_gate_enabled - core/config_store.py): gdy proces
  eurotrucks2.exe nie dziala, klient wchodzi w stan "automatycznie
  wstrzymana" (zero odczytu/sieci, tylko sprawdzanie procesu co ok. 3s) i
  wznawia sam, gdy proces wroci - CHYBA ZE gracz wstrzymal recznie (reczne
  wstrzymanie ma pierwszenstwo, patrz TelemetryWorker.pause()/tick()).

  POLE baseline (kontrakt v5 S3): pierwszy pakiet po KAZDYM wznowieniu
  (recznym i automatycznym) ma "baseline": true (core/ets2_core.py
  build_packet(), sterowane przez TelemetryWorker._pending_baseline).
  Pakiet "v": 5 (bylo 4).

  TOOLTIP ikony zasobnika: teraz DOKLADNIE jeden z 3 tekstow z kontraktu
  ("wysyłka aktywna" / "wstrzymana przez gracza" / "czeka na uruchomienie
  gry" - core/telemetry_worker.py status_text()), ODDZIELNIE od pola
  statusu w oknie (ktore nadal pokazuje szczegolowa diagnostyke -
  status_line()/mem_error_status_line()). Patrz _update_tray_tooltip().

NOWOSCI v0.2.2 (zlecenie koordynatora - ikona zasobnika, autostart,
skrot na pulpicie, pojedyncza instancja):
  - Zasobnik systemowy (pystray + Pillow, core/tray_icon.py): klik ->
    pokaz okno; menu "Pokaz okno" / "Wstrzymaj wysylke lub Wznow" /
    "Wysyłaj tylko gdy gra działa" (v0.2.6) / "Zakoncz". Import pystray
    jest w szerokim try/except (NIE tylko ImportError) - na Linuksie bez
    serwera X pystray rzuca Xlib.error.DisplayNameError przy samym
    imporcie (zweryfikowane w sesji v0.2.2, patrz tests/test_tray_icon.py
    i raport) - program dziala dalej jako zwykle okno, gdy zasobnik sie
    nie uruchomi.
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
  - Start z flaga --tray: okno startuje zminimalizowane do zasobnika;
    wysylka NIE startuje automatycznie (decyzja wlasciciela 2026-11-09,
    wariant B - v0.2.3, BEZ ZMIAN w v0.2.6, patrz kontrakt v5 SS1 pkt 4).
    Status/tooltip po starcie z --tray: "czeka na start wysyłki"
    (TRAY_WAITING_STATUS). Wysylka startuje dopiero, gdy wlasciciel
    kliknie "Zapisz i uruchom" w oknie albo wybierze "Wznów wysyłkę" z
    menu zasobnika.

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
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    autostart,
    config_store,
    game_finder,
    plugin_installer,
    shortcut,
    single_instance,
    telemetry_worker,
    window_controller,
)
from core.ets2_core import CLIENT_VERSION
from core.telemetry_worker import TOKEN_REJECTED_MSG, TelemetryWorker

# Import pystray + core.tray_icon (Pillow) jest w JEDNYM SZEROKIM except
# (nie tylko ImportError) - ZNALEZISKO sesji v0.2.2 (patrz raport): na
# Linuksie bez serwera X pystray rzuca Xlib.error.DisplayNameError juz
# przy samym imporcie; a w buildzie na GitHub Actions z tamtej sesji
# pystray/Pillow NIE zostaly zainstalowane przed krokiem PyInstaller.
# Gdyby ten import byl bezwarunkowy, .exe rozbilby sie zaraz po starcie
# (ModuleNotFoundError: PIL) zamiast dzialac bez zasobnika - stad SZEROKI
# except tutaj obejmuje OBA importy (pystray i core.tray_icon).
try:
    import pystray
    from core.tray_icon import build_icon_image
    TRAY_IMPORT_ERROR: Exception | None = None
except Exception as _e:  # noqa: BLE001 - patrz docstring powyzej
    pystray = None  # type: ignore[assignment]
    build_icon_image = None  # type: ignore[assignment]
    TRAY_IMPORT_ERROR = _e

TRAY_AVAILABLE = pystray is not None and build_icon_image is not None

WINDOW_TITLE = f"ETS2 Szosownia - klient telemetrii v{CLIENT_VERSION}"
TRAY_FLAG = "--tray"
# v0.2.3 (wariant B, BEZ ZMIAN w v0.2.6): tekst statusu/tooltipa zasobnika
# po starcie z --tray, zanim wlasciciel kliknie "Zapisz i uruchom" albo
# "Wznów wysyłkę" (worker jeszcze NIE istnieje w tym momencie).
TRAY_WAITING_STATUS = "czeka na start wysyłki"


def plugin_installed_message(path: str) -> str:
    return f"Plugin zainstalowany w: {path}"


def get_exe_path() -> str:
    """Pelna sciezka do uruchomionego .exe (frozen - PyInstaller) albo do
    tego pliku .py (dev). Uzywane przez autostart (wpis rejestru) i skrot
    na pulpicie (TargetPath)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)


class App:
    def __init__(self, root: tk.Tk, start_hidden: bool = False):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.worker: TelemetryWorker | None = None
        self.game_root: str | None = None
        self.tray_icon = None

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

        # -- v0.2.6: "Wysyłaj tylko gdy gra działa" (kontrakt v5) ---------
        gate_frame = ttk.Frame(frm)
        gate_frame.grid(row=5, column=0, columnspan=2, sticky="we", padx=10)
        self.game_gate_var = tk.BooleanVar(value=True)  # domyslnie WLACZONE
        self.game_gate_chk = ttk.Checkbutton(
            gate_frame,
            text="Wysyłaj tylko gdy gra działa",
            variable=self.game_gate_var,
            command=self.on_toggle_game_gate,
        )
        self.game_gate_chk.pack(side="left")

        ttk.Separator(frm).grid(row=6, column=0, columnspan=2, sticky="we", padx=10, pady=4)

        ttk.Label(frm, text="Status:").grid(row=7, column=0, columnspan=2, sticky="w", padx=10)
        self.status_var = tk.StringVar(value="Gotowy. Wklej token i kliknij „Zapisz i uruchom”.")
        self.status_label = ttk.Label(
            frm, textvariable=self.status_var, wraplength=380, foreground="#222"
        )
        self.status_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))

        self.tray_controller = window_controller.TrayWindowController(
            self.root, tray_available=TRAY_AVAILABLE, on_stop_sending=self._stop_sending_for_quit
        )
        self.root.protocol("WM_DELETE_WINDOW", self.tray_controller.on_window_close_button)

        if TRAY_AVAILABLE:
            self._setup_tray_icon()

        self._load_existing_config()
        self._auto_find_game()

        if start_hidden:
            # v0.2.3 (wariant B, BEZ ZMIAN w v0.2.6): start z --tray TYLKO
            # chowa okno do zasobnika - wysylka NIE startuje automatycznie,
            # nawet gdy jest zapisany token i znaleziona gra. self.worker
            # NIE jest tworzony w tym miejscu - dopiero pierwsze "Zapisz i
            # uruchom"/"Wznów wysyłkę" go utworzy (patrz _resume_sending).
            self.root.withdraw()
            self.tray_controller.visible = False
            self.status_var.set(TRAY_WAITING_STATUS)
            self._update_tray_tooltip(TRAY_WAITING_STATUS)

    # -- zasobnik (pystray) -------------------------------------------------

    def _setup_tray_icon(self):
        """Buduje i startuje ikone zasobnika w osobnym wątku (daemon).
        Kazdy blad (np. brak serwera X na Linuksie) jest chwytany - program
        dziala dalej jako zwykle okno (patrz TRAY_AVAILABLE/docstring)."""
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Pokaż okno", self._on_tray_show, default=True),
                pystray.MenuItem(self._tray_pause_label, self._on_tray_toggle_pause),
                pystray.MenuItem(
                    "Wysyłaj tylko gdy gra działa",
                    self._on_tray_toggle_game_gate,
                    checked=lambda item: self.game_gate_var.get(),
                ),
                pystray.MenuItem("Zakończ", self._on_tray_quit),
            )
            self.tray_icon = pystray.Icon(
                "ets2szosownia", build_icon_image(), self.status_var.get(), menu=menu
            )
            import threading
            self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self._tray_thread.start()
        except Exception:  # noqa: BLE001
            self.tray_icon = None
            self.tray_controller.tray_available = False

    def _tray_pause_label(self, item) -> str:
        # Kontrakt v5 SS1: "Wznów wysyłkę" gdy wstrzymana RECZNIE LUB
        # AUTOMATYCZNIE (albo jeszcze w ogole nie wystartowana - worker
        # is None, np. tuz po starcie z --tray).
        if self.worker is None or self.worker.sending_paused:
            return "Wznów wysyłkę"
        return "Wstrzymaj wysyłkę"

    def _on_tray_show(self, icon, item):
        self.root.after(0, self.tray_controller.show)

    def _on_tray_toggle_pause(self, icon, item):
        self.root.after(0, self._toggle_pause_from_tray)

    def _toggle_pause_from_tray(self):
        if self.worker is None:
            # Jeszcze nigdy nie wystartowano (np. --tray) - "Wznów wysyłkę"
            # z menu robi pelny start (token/gra musza byc juz skonfigurowane
            # z poprzedniego zapisu config.json).
            self.on_save_and_start()
            return
        if self.worker.sending_paused:
            self._resume_sending()
        else:
            self._pause_sending()

    def _on_tray_toggle_game_gate(self, icon, item):
        self.root.after(0, self._toggle_game_gate_from_tray)

    def _toggle_game_gate_from_tray(self):
        self.game_gate_var.set(not self.game_gate_var.get())
        self.on_toggle_game_gate()

    def _on_tray_quit(self, icon, item):
        icon.stop()
        self.root.after(0, self.tray_controller.quit)

    def _stop_sending_for_quit(self):
        """Prawdziwe zatrzymanie watku (koniec programu) - jedyne miejsce,
        ktore wola TelemetryWorker.stop() (w odroznieniu od pause())."""
        if self.worker:
            self.worker.stop()

    # -- pomocnicze -------------------------------------------------------

    def set_status(self, text: str):
        """Wolane z wątku roboczego (diagnostyka szczegolowa - stan gry/
        pamieci SCS) - Tkinter nie jest thread-safe, wiec marshalling przez
        root.after(0, ...). TYLKO pole statusu w oknie - tooltip ikony
        zasobnika jest sterowany ODDZIELNIE przez _update_tray_tooltip()
        (kontrakt v5 SS1: tooltip ma pokazywac dokladnie jeden z 3 ustalonych
        tekstow, nie diagnostyke)."""
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_worker_tooltip(self, text: str):
        """Wolane z wątku roboczego przy KAZDEJ zmianie stanu gatingu
        (pauza/wznowienie/auto-pauza) - ustawia tooltip ikony zasobnika na
        jeden z 3 tekstow kontraktu v5 SS1."""
        self.root.after(0, lambda: self._update_tray_tooltip(text))

    def _update_tray_tooltip(self, text: str):
        if self.tray_icon is not None:
            try:
                self.tray_icon.title = text[:127]  # limit tooltipa Windows
            except Exception:  # noqa: BLE001
                pass

    def _load_existing_config(self):
        cfg = config_store.load_config()
        if cfg:
            self.token_var.set(cfg["token"])
            self.game_gate_var.set(cfg.get("game_gate_enabled", True))
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
        """'Zapisz i uruchom' - instaluje plugin, zapisuje config.json i
        (re)startuje wysylke. v0.2.6: jesli worker juz istnieje (np. byl
        wczesniej wstrzymany przyciskiem 'Zatrzymaj'), NIE tworzy nowego
        watku - tylko podmienia token (update_token) i wznawia (resume()),
        zeby uniknac bledu z v0.2.3-0.2.5 (wielokrotne watki, patrz
        docstring modulu i core/telemetry_worker.py)."""
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
            config_store.save_config(token, game_gate_enabled=self.game_gate_var.get())
        except (OSError, ValueError) as e:
            messagebox.showerror("Błąd zapisu konfiguracji", str(e))
            return

        self.save_btn.config(state="disabled")
        self.choose_btn.config(state="disabled")
        self.token_entry.config(state="disabled")
        self.stop_btn.config(state="normal")

        if self.worker is None:
            self.worker = TelemetryWorker(
                token,
                None,
                self.set_status,
                on_tooltip=self._on_worker_tooltip,
                game_gate_enabled_fn=self.game_gate_var.get,
            )
            self.worker.start()
        else:
            self.worker.update_token(token, None)
        self.worker.resume()

    def on_stop(self):
        """'Zatrzymaj' (przycisk w oknie) - rowniez SOFT pauza (jak tray
        'Wstrzymaj wysyłkę', patrz _pause_sending) - watek NIE jest zabijany,
        tylko wstrzymany (zero odczytu/sieci), zeby ponowne 'Zapisz i
        uruchom' moglo bezpiecznie wznowic bez tworzenia drugiego watku."""
        self._pause_sending()
        self.save_btn.config(state="normal")
        self.choose_btn.config(state="normal")
        self.token_entry.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Zatrzymano przez użytkownika.")

    def _pause_sending(self):
        if self.worker:
            self.worker.pause()

    def _resume_sending(self):
        if self.worker:
            self.worker.resume()
            self.save_btn.config(state="disabled")
            self.choose_btn.config(state="disabled")
            self.token_entry.config(state="disabled")
            self.stop_btn.config(state="normal")

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

    def on_toggle_game_gate(self):
        """Checkbox/menu 'Wysyłaj tylko gdy gra działa' (v0.2.6, kontrakt
        v5). Dziala natychmiast (worker czyta flage na biezaco przez
        game_gate_enabled_fn=self.game_gate_var.get) - nie wymaga
        ponownego 'Zapisz i uruchom'. Jesli token byl juz kiedys zapisany,
        persystuje wybor do config.json od razu."""
        enabled = self.game_gate_var.get()
        cfg = config_store.load_config()
        if cfg:
            try:
                config_store.save_config(
                    cfg["token"],
                    tls_sha256_pin=cfg.get("tls_sha256_pin"),
                    game_gate_enabled=enabled,
                )
            except (OSError, ValueError):
                pass

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
