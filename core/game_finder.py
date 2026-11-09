#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - wyszukiwanie gry (v0.2.0)
===========================================

NOWY KOD (wymagany przez zlecenie koordynatora z 2026-11-09, punkt 3 -
instalator .exe nie moze korzystac z PowerShell/konsoli). Logika jest
PORTEM 1:1 algorytmu z client/install.ps1 (v0.1.3), w tej samej kolejnosci
wyszukiwania:
  a) rejestr Steam (HKCU\\Software\\Valve\\Steam SteamPath,
     HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam InstallPath,
     HKLM\\SOFTWARE\\Valve\\Steam InstallPath)
  b) biblioteki Steam z <SteamPath>\\steamapps\\libraryfolders.vdf (WSZYSTKIE
     biblioteki, rowniez na innych dyskach)
  c) domyslna sciezka C:\\Program Files (x86)\\Steam\\...
  d) wybor folderu przez okno (filedialog) - robi to GUI (app.py), nie ten
     modul; funkcje tutaj sa czyste i testowalne na Linuksie.

Dwie funkcje czysto-tekstowe (parse_vdf_library_paths,
normalize_game_path_input) sa BYTE-FOR-BYTE tym samym algorytmem, co juz
zweryfikowana reimplementacja w client/tests/test_install_logic.py (ktora
z kolei odtwarza install.ps1 1:1) - przeniesione tutaj bez zmian logiki,
tylko jako produkcyjny kod (nie tylko test).

Rejestr Windows (winreg) NIE jest testowany w tej sesji (Linux, brak
winreg) - patrz raport. Import jest osłoniety try/except, zeby modul dal
sie zaimportowac i przetestowac na Linuksie (funkcje czysto-tekstowe +
is_valid_game_root na katalogach tymczasowych).
"""

from __future__ import annotations

import os
import re
import sys

try:
    import winreg  # type: ignore
except ImportError:  # Linux / testy - brak winreg
    winreg = None

GAME_EXE_RELATIVE = os.path.join("bin", "win_x64", "eurotrucks2.exe")
DEFAULT_STEAM_PATH = r"C:\Program Files (x86)\Steam"

_VDF_PATH_RE = re.compile(r'"path"\s*"((?:[^"\\]|\\.)*)"')


# ---------------------------------------------------------------------------
# Funkcje czysto-tekstowe (testowalne na kazdej platformie) - port 1:1
# z install.ps1 / test_install_logic.py.
# ---------------------------------------------------------------------------

def parse_vdf_library_paths(content: str) -> list[str]:
    """Port 1:1 regexu PowerShell '"path"\\s*"((?:[^"\\\\]|\\\\.)*)"' +
    zamiany podwojnego backslasha na pojedynczy (VDF escapuje \\ jako \\\\)."""
    libs: list[str] = []
    for m in _VDF_PATH_RE.finditer(content):
        raw = m.group(1)
        unescaped = raw.replace("\\\\", "\\")
        unescaped = unescaped.rstrip("\\")
        if unescaped and unescaped not in libs:
            libs.append(unescaped)
    return libs


def _split_path(p: str) -> tuple[str, str]:
    """Mirror Split-Path -Parent / -Leaf dla sciezek z backslashem."""
    if "\\" not in p:
        return "", p
    parent, leaf = p.rsplit("\\", 1)
    return parent, leaf


def normalize_game_path_input(input_path: str | None) -> str | None:
    """Port 1:1 Normalize-GamePathInput z install.ps1: akceptuje folder
    gry, folder bin\\win_x64 albo plik eurotrucks2.exe i zwraca folder
    glowny gry."""
    if input_path is None or input_path.strip() == "":
        return None
    p = input_path.strip()
    p = p.strip('"').strip("'").strip()
    p = p.rstrip("\\/")
    if p == "":
        return None
    p = p.replace("/", "\\")

    _, leaf = _split_path(p)
    if leaf.lower() == "eurotrucks2.exe":
        p, leaf = _split_path(p)  # ...\bin\win_x64

    _, leaf = _split_path(p)
    if leaf.lower() == "win_x64":
        parent, _ = _split_path(p)
        _, parent_leaf = _split_path(parent)
        if parent_leaf.lower() == "bin":
            p, _ = _split_path(parent)  # folder gry
    else:
        if leaf.lower() == "bin":
            p, _ = _split_path(p)  # folder gry
    return p


def is_valid_game_root(candidate_dir: str | None) -> str | None:
    """Sprawdza, czy candidate_dir zawiera bin\\win_x64\\eurotrucks2.exe.
    Zwraca znormalizowana sciezke (os.path.abspath) albo None. Mirror
    Test-Ets2Root z install.ps1 - UWAGA: porownanie plikow jest wykonywane
    z separatorem os.sep (dziala rowniez na Linuksie w testach, gdzie
    candidate_dir uzywa '/'); na Windows w produkcji GAME_EXE_RELATIVE
    zawiera '\\', co jest poprawne dla os.path.join na tej platformie."""
    if not candidate_dir:
        return None
    exe_path = os.path.join(candidate_dir, "bin", "win_x64", "eurotrucks2.exe")
    if os.path.isfile(exe_path):
        return os.path.abspath(candidate_dir)
    return None


# ---------------------------------------------------------------------------
# Rejestr Steam + biblioteki (Windows only - winreg)
# ---------------------------------------------------------------------------

def get_steam_paths_from_registry() -> list[str]:
    """Port 1:1 Get-SteamPathsFromRegistry z install.ps1. Na systemach bez
    winreg (Linux) zwraca liste pusta - NIE testowane w tej sesji, patrz
    raport."""
    if winreg is None:
        return []
    found: list[str] = []
    candidates = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, subkey, value_name in candidates:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue  # brak klucza / brak dostepu - normalny przypadek
        if not value:
            continue
        p = str(value).replace("/", "\\").rstrip("\\")
        if p and p not in found:
            found.append(p)
    return found


def get_steam_library_paths(steam_path: str) -> list[str]:
    """Port 1:1 Get-SteamLibraryPaths: steam_path + wszystkie wpisy "path"
    z steamapps\\libraryfolders.vdf."""
    libs: list[str] = []
    if not steam_path or not steam_path.strip():
        return libs
    libs.append(steam_path)

    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        content = None

    if content:
        for lib in parse_vdf_library_paths(content):
            if lib not in libs:
                libs.append(lib)
    return libs


def find_game_root(extra_checked_locations: list[str] | None = None) -> tuple[str | None, list[str]]:
    """Wyszukuje folder glowny ETS2 w kolejnosci a) -> b) -> c) opisanej w
    naglowku modulu. Zwraca (znaleziona_sciezka_albo_None,
    lista_sprawdzonych_lokalizacji) - lista sprawdzonych jest pokazywana w
    oknie GUI, gdy automatyczne wyszukiwanie zawiedzie (krok d: filedialog
    robi GUI)."""
    checked: list[str] = list(extra_checked_locations or [])
    steam_paths = get_steam_paths_from_registry()

    all_libraries: list[str] = []
    for sp in steam_paths:
        for lib in get_steam_library_paths(sp):
            if lib not in all_libraries:
                all_libraries.append(lib)

    for lib in all_libraries:
        candidate = os.path.join(lib, "steamapps", "common", "Euro Truck Simulator 2")
        checked.append(candidate)
        result = is_valid_game_root(candidate)
        if result:
            return result, checked

    default_candidate = os.path.join(
        DEFAULT_STEAM_PATH, "steamapps", "common", "Euro Truck Simulator 2"
    )
    if default_candidate not in checked:
        checked.append(default_candidate)
    result = is_valid_game_root(default_candidate)
    if result:
        return result, checked

    return None, checked
