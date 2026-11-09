#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - skrot na pulpicie (v0.2.2)
=============================================

NOWY KOD. Tworzy plik .lnk na pulpicie uzytkownika przez PowerShell
(WScript.Shell -> CreateShortcut), wywolany przez subprocess z ukrytym
oknem (-WindowStyle Hidden, bez konsoli widocznej dla gracza).

BEZPIECZENSTWO (wymagane przez zlecenie - "bez wstrzykiwania: nie skladaj
komendy ze stringow z konfiguracji; uzyj zmiennych srodowiskowych"):
  - Skrypt PowerShell przekazany do -Command jest STALYM tekstem
    (_SHORTCUT_SCRIPT), NIGDY nie jest budowany przez f-string/format z
    danymi uzytkownika (sciezka do gry/exe, nazwa pliku...).
  - Rzeczywiste wartosci (sciezka docelowa, sciezka skrotu) sa przekazane
    WYLACZNIE przez zmienne srodowiskowe procesu (env=...), odczytywane w
    skrypcie jako $env:ETS2_SHORTCUT_TARGET / $env:ETS2_SHORTCUT_PATH -
    PowerShell traktuje je jako zwykly string (przypisanie do $targetPath
    / $shortcutPath), nie jako kod do wykonania, wiec apostrofy, spacje,
    cudzyslowy czy znaki `;`/`$(...)` w nazwie pliku NIE sa interpretowane.
  - subprocess wolany z lista argumentow (NIE shell=True, NIE jedna
    komenda-string), co dodatkowo wyklucza wstrzykniecie przez shell.

Katalog pulpitu: USERPROFILE\\Desktop, a jesli istnieje (OneDrive moze
przeniesc pulpit) - USERPROFILE\\OneDrive\\Desktop ma priorytet (tam
realnie ladowany jest System.Desktop dla kont z OneDrive Backup).

NIE TESTOWANE na prawdziwym PowerShell/Windows w tej sesji (Linux) -
create_desktop_shortcut() z prawdziwym subprocess.run nigdy nie jest
wywolywane w testach, tylko z wstrzykniety atrapa `runner` - patrz
tests/test_shortcut.py i raport.
"""

from __future__ import annotations

import os
import subprocess
import sys

SHORTCUT_FILE_NAME = "ETS2 Szosownia - Telemetria.lnk"

CREATE_NO_WINDOW = 0x08000000  # Windows: brak mrugajacego okna konsoli

# Skrypt STALY - zero interpolacji danych uzytkownika, patrz docstring.
_SHORTCUT_SCRIPT = (
    "$targetPath = $env:ETS2_SHORTCUT_TARGET\n"
    "$shortcutPath = $env:ETS2_SHORTCUT_PATH\n"
    "$ws = New-Object -ComObject WScript.Shell\n"
    "$sc = $ws.CreateShortcut($shortcutPath)\n"
    "$sc.TargetPath = $targetPath\n"
    "$sc.IconLocation = $targetPath\n"
    "$sc.WorkingDirectory = Split-Path -Parent $targetPath\n"
    "$sc.Save()\n"
)


class ShortcutError(Exception):
    pass


def get_desktop_dir(env: dict | None = None) -> str | None:
    """Zwraca katalog pulpitu albo None, gdy USERPROFILE nie jest
    ustawione (produkcyjnie: zawsze ustawione na Windows). Sprawdza
    USERPROFILE\\OneDrive\\Desktop (jesli istnieje) przed zwyklym
    USERPROFILE\\Desktop."""
    e = env if env is not None else os.environ
    userprofile = e.get("USERPROFILE")
    if not userprofile:
        return None
    onedrive_desktop = os.path.join(userprofile, "OneDrive", "Desktop")
    if os.path.isdir(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(userprofile, "Desktop")


def build_shortcut_env(exe_path: str, shortcut_path: str, base_env: dict | None = None) -> dict:
    """Buduje dict zmiennych srodowiskowych dla subprocess - TU i tylko
    TU wchodza rzeczywiste sciezki (nigdy do listy argumentow/komendy)."""
    env = dict(base_env if base_env is not None else os.environ)
    env["ETS2_SHORTCUT_TARGET"] = exe_path
    env["ETS2_SHORTCUT_PATH"] = shortcut_path
    return env


def create_desktop_shortcut(
    exe_path: str,
    shortcut_name: str = SHORTCUT_FILE_NAME,
    desktop_dir: str | None = None,
    runner=None,
) -> str:
    """Tworzy skrot .lnk na pulpicie wskazujacy na exe_path. Zwraca pelna
    sciezke skrotu. Rzuca ShortcutError z czytelnym komunikatem (bez
    tokena - ta funkcja nie ma dostepu do config.json) przy jakimkolwiek
    bledzie. `runner` (domyslnie subprocess.run) jest wstrzykiwalny -
    testy podaja atrape, zeby nie wolac prawdziwego PowerShell."""
    ddir = desktop_dir if desktop_dir is not None else get_desktop_dir()
    if not ddir:
        raise ShortcutError(
            "Nie znalazlem katalogu pulpitu (brak zmiennej USERPROFILE)."
        )
    try:
        os.makedirs(ddir, exist_ok=True)
    except OSError as e:
        raise ShortcutError(f"Nie moglem utworzyc katalogu pulpitu: {ddir} ({e})")

    shortcut_path = os.path.join(ddir, shortcut_name)
    env = build_shortcut_env(exe_path, shortcut_path)
    run = runner if runner is not None else subprocess.run

    kwargs = dict(
        args=[
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            _SHORTCUT_SCRIPT,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW

    try:
        result = run(**kwargs)
    except OSError as e:
        raise ShortcutError(f"Nie udalo sie uruchomic PowerShell: {e}")
    except subprocess.TimeoutExpired:
        raise ShortcutError("PowerShell nie odpowiedzial w 30 sekund.")

    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or "").strip() or f"kod {result.returncode}"
        raise ShortcutError(f"PowerShell zakonczyl sie bledem: {detail}")

    return shortcut_path
