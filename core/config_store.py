#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - konfiguracja w %APPDATA% (v0.2.0)
====================================================

NOWY KOD. Zlecenie koordynatora: konfiguracja (token, opcjonalny
tls_sha256_pin) w %APPDATA%\\ETS2Szosownia\\config.json, bez edycji
recznej przez gracza. Token NIGDY nie jest wypisywany/logowany - funkcje
tutaj nie maja zadnego print()/logging, zwracaja tylko dict/wyjatki, GUI
decyduje co pokazac (i nigdy nie pokazuje tokena).

server_url jest NA STALE (SERVER_URL w core/ets2_core.py) - nie jest
czescia config.json, zeby gracz nie mogl przypadkiem wpisac innego adresu.
"""

from __future__ import annotations

import json
import os
import stat
import sys

APP_DIR_NAME = "ETS2Szosownia"
CONFIG_FILE_NAME = "config.json"


def get_config_dir() -> str:
    """%APPDATA%\\ETS2Szosownia na Windows. Na innych systemach (testy na
    Linuksie) uzywa $APPDATA jesli ustawione, inaczej ~/.config - WYLACZNIE
    do testow, produkcyjnie program dziala tylko na Windows."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), ".config", APP_DIR_NAME)


def get_config_path(config_dir: str | None = None) -> str:
    return os.path.join(config_dir or get_config_dir(), CONFIG_FILE_NAME)


def load_config(config_dir: str | None = None) -> dict | None:
    """Zwraca dict {'token':..., 'tls_sha256_pin': ... (opcjonalny)} albo
    None, gdy plik nie istnieje jeszcze (pierwsze uruchomienie - GUI pokaze
    puste pole tokena). Plik uszkodzony (zly JSON) -> None, tak jak brak
    pliku (GUI poprosi o ponowne wklejenie tokena, zamiast siadac)."""
    path = get_config_path(config_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("token"):
        return None
    result = {"token": str(cfg["token"])}
    pin = cfg.get("tls_sha256_pin")
    if pin:
        result["tls_sha256_pin"] = str(pin)
    return result


def save_config(token: str, tls_sha256_pin: str | None = None,
                 config_dir: str | None = None) -> str:
    """Zapisuje config.json, tworzac katalog %APPDATA%\\ETS2Szosownia przy
    pierwszym zapisie. tls_sha256_pin domyslnie NIE jest zapisywany
    (zgodnie ze zleceniem - gracz nie musi znac tego mechanizmu). Zwraca
    sciezke zapisanego pliku. Nie loguje/wypisuje tokena nigdzie."""
    if not token or not token.strip():
        raise ValueError("Token nie moze byc pusty.")
    cdir = config_dir or get_config_dir()
    os.makedirs(cdir, exist_ok=True)
    path = get_config_path(cdir)
    cfg = {"token": token.strip()}
    if tls_sha256_pin:
        cfg["tls_sha256_pin"] = tls_sha256_pin.strip()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    # Windows nie ma trybu POSIX 600, ale na systemach, ktore go wspieraja
    # (testy na Linuksie) ograniczamy uprawnienia do odczytu/zapisu wlasciciela.
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path
