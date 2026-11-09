#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - pojedyncza instancja (v0.2.2)
=================================================

NOWY KOD. Wybor (patrz zlecenie, punkt 4 - "wybierz jedno, opisz w
raporcie"): NAMED MUTEX przez ctypes CreateMutexW, nazwa
"ETS2SzosowniaTelemetria". Powod wyboru nad gniazdem localhost: mutex jest
automatycznie zwalniany przez system przy zakonczeniu/awarii procesu (bez
ryzyka "zombie" portu zajetego po zabiciu procesu w Managerze Zadan), nie
wymaga wyboru/wolnego portu i nie styka sie z firewallem/antywirusem tak
jak nowe gniazdo nasluchujace.

Druga uruchomiona instancja: acquire() zwraca False (GetLastError() ==
ERROR_ALREADY_EXISTS), program wtedy probuje przywolac okno pierwszej
instancji przez FindWindowW(tytul okna) + ShowWindow/SetForegroundWindow
(dziala, bo tkinter tworzy prawdziwy natywny HWND z tytulem = WINDOW_TITLE
z app.py) i kolejny proces sie zamyka - NIE tworzy drugiego klienta.

WinAPI jest Windows-only. Wszystkie funkcje przyjmuja opcjonalny
`kernel32`/`user32` (duck-typing, taki sam wzorzec jak core/ets2_core.py
_configure_kernel32) - testy (tests/test_single_instance.py) wstrzykuja
atrape. NIE TESTOWANE na prawdziwym WinAPI/Windows w tej sesji (Linux) -
patrz raport.
"""

from __future__ import annotations

import ctypes as C
import sys

MUTEX_NAME = "ETS2SzosowniaTelemetria"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


def _real_kernel32():
    if sys.platform != "win32":
        return None
    kernel32 = C.windll.kernel32
    kernel32.CreateMutexW.argtypes = (C.c_void_p, C.c_int, C.c_wchar_p)
    kernel32.CreateMutexW.restype = C.c_void_p
    kernel32.GetLastError.argtypes = ()
    kernel32.GetLastError.restype = C.c_uint32
    kernel32.CloseHandle.argtypes = (C.c_void_p,)
    kernel32.CloseHandle.restype = C.c_int
    return kernel32


def _real_user32():
    if sys.platform != "win32":
        return None
    user32 = C.windll.user32
    user32.FindWindowW.argtypes = (C.c_wchar_p, C.c_wchar_p)
    user32.FindWindowW.restype = C.c_void_p
    user32.ShowWindow.argtypes = (C.c_void_p, C.c_int)
    user32.ShowWindow.restype = C.c_int
    user32.SetForegroundWindow.argtypes = (C.c_void_p,)
    user32.SetForegroundWindow.restype = C.c_int
    return user32


class SingleInstanceGuard:
    """is_primary == True -> jestesmy pierwsza (jedyna) instancja, program
    moze normalnie startowac. is_primary == False -> druga instancja,
    program powinien przywolac okno pierwszej i zakonczyc sie."""

    def __init__(self, name: str = MUTEX_NAME):
        self.name = name
        self.is_primary: bool | None = None
        self._handle = None
        self._kernel32 = None

    def acquire(self, kernel32=None) -> bool:
        k32 = kernel32 if kernel32 is not None else _real_kernel32()
        if k32 is None:
            # nie-Windows (testy logiki na Linuksie uzywaja atrapy powyzej,
            # a nie tej sciezki) - zawsze "primary", nie ma czego pilnowac.
            self.is_primary = True
            return True
        self._kernel32 = k32
        handle = k32.CreateMutexW(None, False, self.name)
        last_error = k32.GetLastError()
        self._handle = handle
        self.is_primary = handle not in (None, 0) and last_error != ERROR_ALREADY_EXISTS
        return self.is_primary

    def release(self) -> None:
        if self._handle and self._kernel32 is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def try_focus_existing_window(window_title: str, user32=None) -> bool:
    """Szuka okna o tytule window_title (FindWindowW) i probuje je
    przywrocic/wysunac na pierwszy plan. Zwraca True, jesli okno
    znaleziono (niezaleznie od tego, czy ShowWindow/SetForegroundWindow
    sie w pelni powiodly - to tylko najlepszy mozliwy wysilek)."""
    u32 = user32 if user32 is not None else _real_user32()
    if u32 is None:
        return False
    hwnd = u32.FindWindowW(None, window_title)
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, SW_RESTORE)
    u32.SetForegroundWindow(hwnd)
    return True
