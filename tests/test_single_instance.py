#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy pojedynczej instancji (v0.2.2) na atrapach kernel32/user32 (Linux
nie ma prawdziwego WinAPI - patrz raport dla testu na prawdziwym Windows)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import single_instance  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


class FakeKernel32First:
    """Symuluje PIERWSZA instancje: CreateMutexW tworzy nowy mutex,
    GetLastError() == 0 (ERROR_SUCCESS)."""

    def CreateMutexW(self, security, initial_owner, name):
        return 12345  # falszywy, niezerowy "handle"

    def GetLastError(self):
        return 0

    def CloseHandle(self, handle):
        self.closed = handle


class FakeKernel32Second:
    """Symuluje DRUGA instancje: CreateMutexW zwraca handle ISTNIEJACEGO
    mutexu, GetLastError() == ERROR_ALREADY_EXISTS (183)."""

    def CreateMutexW(self, security, initial_owner, name):
        return 12345

    def GetLastError(self):
        return single_instance.ERROR_ALREADY_EXISTS

    def CloseHandle(self, handle):
        pass


def test_first_instance_acquires_mutex():
    guard = single_instance.SingleInstanceGuard()
    result = guard.acquire(kernel32=FakeKernel32First())
    check("pierwsza instancja: acquire() -> True", result, True)
    check("guard.is_primary == True", guard.is_primary, True)


def test_second_instance_detects_existing_mutex():
    guard = single_instance.SingleInstanceGuard()
    result = guard.acquire(kernel32=FakeKernel32Second())
    check("druga instancja: acquire() -> False", result, False)
    check("guard.is_primary == False", guard.is_primary, False)


def test_release_closes_handle_only_when_acquired_on_windows():
    guard = single_instance.SingleInstanceGuard()
    fake = FakeKernel32First()
    guard.acquire(kernel32=fake)
    guard.release()
    check("release() woła CloseHandle na uchwycie", getattr(fake, "closed", None), 12345)
    check("po release() _handle wyczyszczony", guard._handle, None)


def test_non_windows_without_fake_is_always_primary():
    """Na Linuksie bez atrapy (produkcyjna sciezka _real_kernel32() ->
    None na nie-Windows) - zawsze "pierwsza instancja"."""
    if sys.platform == "win32":
        print("[SKIP] test tylko na nie-Windows")
        return
    guard = single_instance.SingleInstanceGuard()
    result = guard.acquire()
    check("nie-Windows bez atrapy -> acquire() True", result, True)


class FakeUser32Found:
    def __init__(self):
        self.calls = []

    def FindWindowW(self, cls, title):
        self.calls.append(("FindWindowW", cls, title))
        return 999

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("ShowWindow", hwnd, cmd))
        return 1

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        return 1


class FakeUser32NotFound:
    def FindWindowW(self, cls, title):
        return 0

    def ShowWindow(self, hwnd, cmd):
        raise AssertionError("nie powinno byc wolane, gdy okno nie istnieje")

    def SetForegroundWindow(self, hwnd):
        raise AssertionError("nie powinno byc wolane, gdy okno nie istnieje")


def test_try_focus_existing_window_found():
    fake = FakeUser32Found()
    result = single_instance.try_focus_existing_window("ETS2 Szosownia", user32=fake)
    check("okno znalezione -> True", result, True)
    check(
        "wywolano ShowWindow + SetForegroundWindow",
        [c[0] for c in fake.calls[1:]],
        ["ShowWindow", "SetForegroundWindow"],
    )


def test_try_focus_existing_window_not_found():
    fake = FakeUser32NotFound()
    result = single_instance.try_focus_existing_window("Nieistniejace okno", user32=fake)
    check("okno nieznalezione -> False", result, False)


if __name__ == "__main__":
    test_first_instance_acquires_mutex()
    test_second_instance_detects_existing_mutex()
    test_release_closes_handle_only_when_acquired_on_windows()
    test_non_windows_without_fake_is_always_primary()
    test_try_focus_existing_window_found()
    test_try_focus_existing_window_not_found()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy pojedynczej instancji (atrapy kernel32/user32) przeszły")
