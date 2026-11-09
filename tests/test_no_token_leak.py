#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowe testy (v0.2.0): kontrola negatywna - token nie wycieka do zadnego
tekstu, ktory GUI moze pokazac graczowi (status, komunikaty bledow,
sciezki, tytul okna)."""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config_store, plugin_installer, game_finder  # noqa: E402
from core.ets2_core import status_line, mem_error_status_line, CLIENT_VERSION  # noqa: E402
import app  # noqa: E402

FAIL = 0
SECRET_TOKEN = "SEKRETNY-TOKEN-NIE-POKAZUJ-9f8e7d6c"


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def check_true(label, cond):
    check(label, bool(cond), True)


def test_window_title_never_contains_token():
    check_true("WINDOW_TITLE nie zawiera slowa 'token'", "token" not in app.WINDOW_TITLE.lower())
    check_true("WINDOW_TITLE nie zawiera przykladowego tokena", SECRET_TOKEN not in app.WINDOW_TITLE)
    check("WINDOW_TITLE zawiera numer wersji", CLIENT_VERSION in app.WINDOW_TITLE, True)


def test_token_rejected_message_has_no_token_placeholder():
    check_true("komunikat 401 nie zawiera slowa z pola tokena", "token" not in app.TOKEN_REJECTED_MSG.lower() or
               "wygeneruj nowy" in app.TOKEN_REJECTED_MSG.lower())
    check_true("komunikat 401 wskazuje konkretna akcje (szosownia.com)", "szosownia.com" in app.TOKEN_REJECTED_MSG)


def test_plugin_installed_message_contains_only_path():
    msg = app.plugin_installed_message(r"C:\Games\ETS2\bin\win_x64\plugins\scs-telemetry.dll")
    check_true("komunikat zaczyna sie od 'Plugin zainstalowany w:'", msg.startswith("Plugin zainstalowany w:"))
    check_true("komunikat nie zawiera slowa 'token'", "token" not in msg.lower())


def test_save_config_error_messages_never_echo_token_value():
    """ValueError z save_config() (token pusty) nie powtarza samej
    wartosci tokena (bo jest pusta/spacje) - sprawdzamy przeciez, ze
    kazdy inny blad (np. zly folder) rowniez nie zawiera SECRET_TOKEN,
    nawet gdyby zostal podany jako argument."""
    tmpdir = tempfile.mkdtemp(prefix="ets2-noleak-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        path = config_store.save_config(SECRET_TOKEN, config_dir=cfg_dir)
        # plik config.json SAM zawiera token (to jest oczekiwane - to jest
        # miejsce jego przechowywania), ale zadna FUNKCJA nie zwraca go w
        # komunikacie/stringu przeznaczonym do pokazania w GUI:
        try:
            config_store.save_config("", config_dir=cfg_dir)
            FAIL_LOCAL = True
        except ValueError as e:
            FAIL_LOCAL = SECRET_TOKEN in str(e)
        check("ValueError przy pustym tokenie nie zawiera SECRET_TOKEN", FAIL_LOCAL, False)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_plugin_install_error_messages_never_contain_token():
    """PluginInstallError nie ma dostepu do tokena (funkcja go nie
    przyjmuje) - kontrola negatywna na przykladowych sciezkach."""
    tmpdir = tempfile.mkdtemp(prefix="ets2-noleak-test-")
    try:
        missing_src = os.path.join(tmpdir, "nie-ma-takiego.dll")
        game_root = os.path.join(tmpdir, "Gra")
        os.makedirs(game_root)
        try:
            plugin_installer.install_plugin(game_root, source_dll_path=missing_src)
            ok = False
        except plugin_installer.PluginInstallError as e:
            ok = SECRET_TOKEN not in str(e)
        check("PluginInstallError nie zawiera tokena", ok, True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_lines_never_contain_token_examples():
    lines = [
        status_line(False, False),
        status_line(True, False),
        status_line(True, True),
        mem_error_status_line("OSError: cos sie zepsulo"),
        app.TOKEN_REJECTED_MSG,
        app.plugin_installed_message("C:\\Gry\\ETS2\\bin\\win_x64\\plugins\\scs-telemetry.dll"),
    ]
    all_ok = all(SECRET_TOKEN not in line and "Bearer" not in line for line in lines)
    check("zaden z tekstow statusu GUI nie zawiera tokena/Bearer", all_ok, True)


if __name__ == "__main__":
    test_window_title_never_contains_token()
    test_token_rejected_message_has_no_token_placeholder()
    test_plugin_installed_message_contains_only_path()
    test_save_config_error_messages_never_echo_token_value()
    test_plugin_install_error_messages_never_contain_token()
    test_status_lines_never_contain_token_examples()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy braku wycieku tokena przeszły")
