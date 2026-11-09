#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowe testy (v0.2.0): kopiowanie DLL do katalogu tymczasowego (nie
prawdziwej gry) + weryfikacja SHA-256."""
import hashlib
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import plugin_installer  # noqa: E402

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


ASSETS_DLL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "scs-telemetry.dll")


def test_real_bundled_dll_matches_expected_sha256():
    check_true("assets/scs-telemetry.dll istnieje w repo", os.path.isfile(ASSETS_DLL))
    actual = plugin_installer.sha256_of_file(ASSETS_DLL)
    check(
        "SHA-256 pliku w assets/ zgadza sie z EXPECTED_SHA256",
        actual.lower(),
        plugin_installer.EXPECTED_SHA256.lower(),
    )


def test_install_plugin_copies_and_verifies_into_tmp_game_root():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        os.makedirs(game_root)
        target = plugin_installer.install_plugin(game_root, source_dll_path=ASSETS_DLL)
        check_true("sciezka zwrocona istnieje", os.path.isfile(target))
        check_true(
            "sciezka docelowa to bin\\win_x64\\plugins\\scs-telemetry.dll",
            target.replace("\\", "/").endswith("bin/win_x64/plugins/scs-telemetry.dll"),
        )
        actual_sha = plugin_installer.sha256_of_file(target)
        check("SHA-256 skopiowanego pliku zgadza sie z oczekiwanym", actual_sha.lower(), plugin_installer.EXPECTED_SHA256.lower())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_install_plugin_creates_plugins_dir_if_missing():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        plugins_dir = os.path.join(game_root, "bin", "win_x64", "plugins")
        check_true("folder plugins nie istnieje przed instalacja", not os.path.isdir(plugins_dir))
        os.makedirs(game_root)
        plugin_installer.install_plugin(game_root, source_dll_path=ASSETS_DLL)
        check_true("folder plugins zostal utworzony", os.path.isdir(plugins_dir))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_install_plugin_replaces_old_version_with_different_hash():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        plugins_dir = os.path.join(game_root, "bin", "win_x64", "plugins")
        os.makedirs(plugins_dir)
        old_path = os.path.join(plugins_dir, "scs-telemetry.dll")
        with open(old_path, "wb") as f:
            f.write(b"STARA-WERSJA-PLUGINU-INNA-SUMA")
        old_sha = plugin_installer.sha256_of_file(old_path)

        target = plugin_installer.install_plugin(game_root, source_dll_path=ASSETS_DLL)
        new_sha = plugin_installer.sha256_of_file(target)
        check_true("suma pliku ZMIENILA sie (podmiana starej wersji)", new_sha != old_sha)
        check("nowa suma zgadza sie z oczekiwana", new_sha.lower(), plugin_installer.EXPECTED_SHA256.lower())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_install_plugin_is_idempotent_when_already_correct():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        os.makedirs(game_root)
        target1 = plugin_installer.install_plugin(game_root, source_dll_path=ASSETS_DLL)
        mtime1 = os.path.getmtime(target1)
        target2 = plugin_installer.install_plugin(game_root, source_dll_path=ASSETS_DLL)
        check("druga instalacja zwraca ta sama sciezke", target2, target1)
        check_true("plik nie zostal ponownie skopiowany (sama suma -> brak kopiowania)",
                    os.path.getmtime(target2) == mtime1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_install_plugin_rejects_corrupted_source():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        os.makedirs(game_root)
        fake_src = os.path.join(tmpdir, "fake.dll")
        with open(fake_src, "wb") as f:
            f.write(b"TO NIE JEST PRAWDZIWY PLUGIN")
        try:
            plugin_installer.install_plugin(game_root, source_dll_path=fake_src)
            print("[FAIL] oczekiwano PluginInstallError dla uszkodzonego zrodla")
            global FAIL
            FAIL += 1
        except plugin_installer.PluginInstallError as e:
            ok = "SHA-256" in str(e)
            print(f"[{'OK ' if ok else 'FAIL'}] uszkodzone zrodlo -> PluginInstallError: {e}")
            FAIL += 0 if ok else 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_install_plugin_missing_source_file_raises_clear_error():
    tmpdir = tempfile.mkdtemp(prefix="ets2-plugin-test-")
    try:
        game_root = os.path.join(tmpdir, "Euro Truck Simulator 2")
        os.makedirs(game_root)
        missing_src = os.path.join(tmpdir, "nie-istnieje.dll")
        try:
            plugin_installer.install_plugin(game_root, source_dll_path=missing_src)
            print("[FAIL] oczekiwano PluginInstallError dla brakujacego zrodla")
            global FAIL
            FAIL += 1
        except plugin_installer.PluginInstallError as e:
            print(f"[OK ] brak zrodla -> PluginInstallError: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_real_bundled_dll_matches_expected_sha256()
    test_install_plugin_copies_and_verifies_into_tmp_game_root()
    test_install_plugin_creates_plugins_dir_if_missing()
    test_install_plugin_replaces_old_version_with_different_hash()
    test_install_plugin_is_idempotent_when_already_correct()
    test_install_plugin_rejects_corrupted_source()
    test_install_plugin_missing_source_file_raises_clear_error()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy plugin_installer przeszły")
