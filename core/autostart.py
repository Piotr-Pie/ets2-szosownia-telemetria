#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - autostart z Windows (v0.2.2)
===============================================

NOWY KOD. Zapisuje/usuwa wpis w HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Run, tak zeby .exe startowal razem z Windows (checkbox w
app.py "Uruchamiaj razem z Windows", DOMYSLNIE WYLACZONY).

Wartosc rejestru: nazwa "ETS2Szosownia", dane: '"<pelna sciezka do exe>"
--tray' (cudzyslowy wokol sciezki - wymagane, bo sciezka moze zawierac
spacje; "--tray" nakazuje programowi wystartowac od razu zminimalizowany
do zasobnika, patrz core/tray_icon.py i app.py).

Rejestr (winreg) jest Windows-only. Na Linuksie (ta sesja) winreg nie
istnieje - import jest oslonie ty try/except i WSZYSTKIE funkcje przyjmuja
opcjonalny parametr `registry` (duck-typing: obiekt z OpenKey/CreateKeyEx/
SetValueEx/DeleteValue/QueryValueEx i stalymi HKEY_CURRENT_USER/
KEY_SET_VALUE/KEY_READ/REG_SZ) - testy (tests/test_autostart.py) wstrzykuja
atrape zamiast prawdziwego winreg. NIE TESTOWANE na prawdziwym rejestrze
Windows w tej sesji - patrz raport.
"""

from __future__ import annotations

import sys

try:
    import winreg  # type: ignore
except ImportError:  # Linux - brak winreg, patrz docstring
    winreg = None  # type: ignore

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ETS2Szosownia"
TRAY_FLAG = "--tray"


def build_autostart_command(exe_path: str) -> str:
    """Zwraca dokladna wartosc wpisana do rejestru: sciezka w cudzyslowach
    + flaga --tray. Funkcja CZYSTA (testowalna bez rejestru)."""
    return f'"{exe_path}" {TRAY_FLAG}'


def _registry_or_default(registry):
    return registry if registry is not None else winreg


def is_autostart_supported(registry=None) -> bool:
    """False na Linuksie (brak winreg i brak atrapy podanej w testach)."""
    return _registry_or_default(registry) is not None


def enable_autostart(exe_path: str, registry=None) -> None:
    """Tworzy/nadpisuje wpis autostartu. No-op (bez wyjatku), gdy rejestr
    jest niedostepny (nie-Windows, produkcyjnie nie powinno sie zdarzyc)."""
    reg = _registry_or_default(registry)
    if reg is None:
        return
    command = build_autostart_command(exe_path)
    key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, reg.KEY_SET_VALUE)
    try:
        reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command)
    finally:
        reg.CloseKey(key) if hasattr(reg, "CloseKey") else None


def disable_autostart(registry=None) -> None:
    """Usuwa wpis autostartu, jesli istnieje. Brak wpisu / brak rejestru
    NIE jest bledem (checkbox wylaczony od zawsze jest normalnym stanem)."""
    reg = _registry_or_default(registry)
    if reg is None:
        return
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, reg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        try:
            reg.DeleteValue(key, VALUE_NAME)
        except OSError:
            pass  # wpisu i tak nie bylo
    finally:
        reg.CloseKey(key) if hasattr(reg, "CloseKey") else None


def is_autostart_enabled(registry=None) -> bool:
    """Zwraca True, gdy wpis istnieje (niezaleznie od dokladnej treci -
    checkbox w GUI odzwierciedla tylko obecnosc wpisu)."""
    reg = _registry_or_default(registry)
    if reg is None:
        return False
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, reg.KEY_READ)
    except OSError:
        return False
    try:
        try:
            value, _ = reg.QueryValueEx(key, VALUE_NAME)
        except OSError:
            return False
        return bool(value)
    finally:
        reg.CloseKey(key) if hasattr(reg, "CloseKey") else None
