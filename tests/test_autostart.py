#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy autostartu (v0.2.2) na atrapie winreg (Linux nie ma prawdziwego
rejestru Windows - patrz raport dla testu na prawdziwym Windows)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import autostart  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def check_true(label, cond):
    check(label, bool(cond), True)


class FakeKey:
    def __init__(self, store, hive_name):
        self.store = store
        self.hive_name = hive_name


class FakeWinReg:
    """Atrapa winreg: przechowuje wartosci w dict {(hive, path, name): value}."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 0x2
    KEY_READ = 0x1
    REG_SZ = 1

    def __init__(self):
        self.values: dict[tuple, str] = {}
        self.open_calls = []

    def CreateKeyEx(self, hive, path, reserved, access):
        self.open_calls.append(("CreateKeyEx", hive, path))
        return FakeKey(self, hive)

    def OpenKey(self, hive, path, reserved=0, access=0):
        self.open_calls.append(("OpenKey", hive, path))
        if (hive, path) not in getattr(self, "_existing_keys", set()):
            # pozwalamy OpenKey zawsze - klucz Run zazwyczaj istnieje
            pass
        return FakeKey(self, hive)

    def SetValueEx(self, key, name, reserved, reg_type, value):
        self.values[(key.hive_name, autostart.RUN_KEY_PATH, name)] = value

    def QueryValueEx(self, key, name):
        k = (key.hive_name, autostart.RUN_KEY_PATH, name)
        if k not in self.values:
            raise OSError("wartosc nie istnieje")
        return self.values[k], self.REG_SZ

    def DeleteValue(self, key, name):
        k = (key.hive_name, autostart.RUN_KEY_PATH, name)
        if k not in self.values:
            raise OSError("wartosc nie istnieje")
        del self.values[k]

    def CloseKey(self, key):
        pass


def test_build_autostart_command_has_quotes_and_tray_flag():
    cmd = autostart.build_autostart_command(r"C:\Program Files\ETS2 Szosownia\app.exe")
    check(
        "komenda autostartu (cudzyslowy + --tray)",
        cmd,
        '"C:\\Program Files\\ETS2 Szosownia\\app.exe" --tray',
    )


def test_enable_creates_registry_value():
    fake = FakeWinReg()
    exe_path = r"C:\Users\Gracz\AppData\Local\ETS2Szosownia\app.exe"
    autostart.enable_autostart(exe_path, registry=fake)
    stored = fake.values.get((fake.HKEY_CURRENT_USER, autostart.RUN_KEY_PATH, autostart.VALUE_NAME))
    check("wpis zapisany z cudzyslowami i --tray", stored, f'"{exe_path}" --tray')


def test_is_enabled_reflects_registry_state():
    fake = FakeWinReg()
    check("przed zapisem: nieaktywny", autostart.is_autostart_enabled(registry=fake), False)
    autostart.enable_autostart(r"C:\app.exe", registry=fake)
    check("po zapisie: aktywny", autostart.is_autostart_enabled(registry=fake), True)


def test_disable_removes_registry_value():
    fake = FakeWinReg()
    autostart.enable_autostart(r"C:\app.exe", registry=fake)
    check_true("wpis istnieje przed wylaczeniem", autostart.is_autostart_enabled(registry=fake))
    autostart.disable_autostart(registry=fake)
    check("wpis usuniety po wylaczeniu", autostart.is_autostart_enabled(registry=fake), False)


def test_disable_without_existing_entry_does_not_raise():
    fake = FakeWinReg()
    try:
        autostart.disable_autostart(registry=fake)
        print("[OK ] disable_autostart na pustym rejestrze nie rzuca wyjatku")
    except Exception as e:  # noqa: BLE001
        global FAIL
        FAIL += 1
        print(f"[FAIL] disable_autostart rzucilo wyjatek: {e!r}")


def test_no_registry_on_linux_is_safe_noop():
    """Bez atrapy i bez winreg (Linux) - funkcje nie rzucaja wyjatkow."""
    if autostart.winreg is not None:
        print("[SKIP] winreg jest dostepny w tym srodowisku (nieoczekiwane na Linuksie)")
        return
    try:
        autostart.enable_autostart(r"C:\app.exe")
        autostart.disable_autostart()
        check("is_autostart_enabled() bez winreg -> False", autostart.is_autostart_enabled(), False)
        check("is_autostart_supported() bez winreg -> False", autostart.is_autostart_supported(), False)
    except Exception as e:  # noqa: BLE001
        global FAIL
        FAIL += 1
        print(f"[FAIL] no-op bez winreg rzucilo wyjatek: {e!r}")


if __name__ == "__main__":
    test_build_autostart_command_has_quotes_and_tray_flag()
    test_enable_creates_registry_value()
    test_is_enabled_reflects_registry_state()
    test_disable_removes_registry_value()
    test_disable_without_existing_entry_does_not_raise()
    test_no_registry_on_linux_is_safe_noop()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy autostartu (atrapa winreg) przeszły")
