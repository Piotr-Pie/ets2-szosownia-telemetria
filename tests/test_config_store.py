#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowe testy (v0.2.0): zapis/odczyt config.json w katalogu tymczasowym
(nigdy w prawdziwym %APPDATA% tego hosta)."""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config_store  # noqa: E402

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


def test_load_returns_none_when_file_missing():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")  # katalog NIE istnieje jeszcze
        result = config_store.load_config(config_dir=cfg_dir)
        check("brak pliku -> load_config zwraca None", result, None)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_save_creates_directory_on_first_write():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        check_true("katalog nie istnieje przed zapisem", not os.path.isdir(cfg_dir))
        path = config_store.save_config("moj-tajny-token-abc", config_dir=cfg_dir)
        check_true("katalog zostal utworzony przy pierwszym zapisie", os.path.isdir(cfg_dir))
        check_true("plik config.json istnieje", os.path.isfile(path))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_save_and_load_roundtrip_token_only():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        config_store.save_config("abc-123-token", config_dir=cfg_dir)
        loaded = config_store.load_config(config_dir=cfg_dir)
        check("token odczytany tak jak zapisany", loaded["token"], "abc-123-token")
        check_true("tls_sha256_pin NIEUSTAWIONY domyslnie", "tls_sha256_pin" not in loaded)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_save_and_load_roundtrip_with_pin():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        pin = "a" * 64
        config_store.save_config("tok", tls_sha256_pin=pin, config_dir=cfg_dir)
        loaded = config_store.load_config(config_dir=cfg_dir)
        check("pin odczytany tak jak zapisany (gdy jawnie podany)", loaded.get("tls_sha256_pin"), pin)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_save_empty_token_raises():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        try:
            config_store.save_config("   ", config_dir=cfg_dir)
            print("[FAIL] oczekiwano ValueError dla pustego tokena")
            global FAIL
            FAIL += 1
        except ValueError:
            print("[OK ] pusty token -> ValueError, zgodnie z oczekiwaniem")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_corrupted_json_treated_as_missing():
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        os.makedirs(cfg_dir)
        with open(config_store.get_config_path(cfg_dir), "w", encoding="utf-8") as f:
            f.write("{to nie jest poprawny json")
        result = config_store.load_config(config_dir=cfg_dir)
        check("JSON uszkodzony -> load_config zwraca None (nie wyjatek)", result, None)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_config_file_never_contains_server_url_field():
    """server_url jest na stale w kodzie (SERVER_URL), NIE w config.json -
    sprawdzamy, ze save_config() nigdy go tam nie wpisuje."""
    tmpdir = tempfile.mkdtemp(prefix="ets2-config-test-")
    try:
        cfg_dir = os.path.join(tmpdir, "ETS2Szosownia")
        path = config_store.save_config("tok-xyz", config_dir=cfg_dir)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        check_true("'server_url' nie jest kluczem w config.json", "server_url" not in raw)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_load_returns_none_when_file_missing()
    test_save_creates_directory_on_first_write()
    test_save_and_load_roundtrip_token_only()
    test_save_and_load_roundtrip_with_pin()
    test_save_empty_token_raises()
    test_corrupted_json_treated_as_missing()
    test_config_file_never_contains_server_url_field()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy config_store przeszły")
