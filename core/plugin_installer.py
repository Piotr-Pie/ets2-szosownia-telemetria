#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - instalacja pluginu DLL (v0.2.0)
==================================================

NOWY KOD. DLL jest wbudowany w plik .exe przez PyInstaller --add-data
(patrz build.spec: ('../client/scs-telemetry.dll' skopiowany lokalnie do
assets/scs-telemetry.dll, 'assets')). W trybie frozen (PyInstaller)
sciezka do zasobow to sys._MEIPASS; w trybie deweloperskim/testowym to
katalog assets/ wzgledem tego pliku.

SHA-256 oczekiwany (ten sam plik co w client/scs-telemetry.dll, v0.1.3,
zweryfikowany w tej sesji przez sha256sum):
  d8d273d21759a53c09320d5375d0b7cc871aab1d69bbebefc86a14a5e53ca454

Logika kopiowania jest portem Copy-Item + Get-FileHash z install.ps1:
tworzy bin\\win_x64\\plugins jesli nie istnieje, kopiuje, liczy SHA-256 PO
skopiowaniu i podmienia plik, jesli juz istniejacy plik w grze ma inna
sume (np. stara wersja pluginu) - weryfikacja/podmiana dziala identycznie
niezaleznie od tego, czy docelowy plik istnial wczesniej.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys

EXPECTED_SHA256 = "d8d273d21759a53c09320d5375d0b7cc871aab1d69bbebefc86a14a5e53ca454"
DLL_NAME = "scs-telemetry.dll"
PLUGIN_RELATIVE_DIR = os.path.join("bin", "win_x64", "plugins")


class PluginInstallError(Exception):
    pass


def _bundled_dll_path() -> str:
    """Sciezka do DLL wbudowanego w .exe (frozen) albo do assets/ lokalnie
    (dev / testy)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", DLL_NAME)  # type: ignore[attr-defined]
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "assets", DLL_NAME)


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_plugin(game_root: str, source_dll_path: str | None = None,
                    expected_sha256: str = EXPECTED_SHA256) -> str:
    """Kopiuje DLL do <game_root>\\bin\\win_x64\\plugins\\scs-telemetry.dll,
    tworzac katalog docelowy, jesli trzeba. Weryfikuje SHA-256 pliku
    ZRODLOWEGO zanim kopiuje (chroni przed wbudowaniem uszkodzonego pliku w
    .exe) i SHA-256 pliku DOCELOWEGO po skopiowaniu (chroni przed
    uszkodzeniem w trakcie kopiowania). Jesli plik docelowy juz istnieje z
    INNA suma (stara wersja) - jest podmieniany. Zwraca pelna sciezke pliku
    docelowego. Rzuca PluginInstallError z czytelnym komunikatem (po
    polsku, bez tokena - ta funkcja nie ma dostepu do config.json) przy
    jakimkolwiek bledzie."""
    src = source_dll_path or _bundled_dll_path()
    if not os.path.isfile(src):
        raise PluginInstallError(
            f"Nie znaleziono wbudowanego pliku pluginu: {src}"
        )
    actual_src_sha = sha256_of_file(src)
    if actual_src_sha.lower() != expected_sha256.lower():
        raise PluginInstallError(
            "Plugin wbudowany w instalator ma nieprawidlowa sume SHA-256 "
            f"(oczekiwano {expected_sha256}, otrzymano {actual_src_sha}). "
            "Pobierz instalator ponownie - plik jest uszkodzony."
        )

    plugin_dir = os.path.join(game_root, PLUGIN_RELATIVE_DIR)
    target = os.path.join(plugin_dir, DLL_NAME)

    try:
        os.makedirs(plugin_dir, exist_ok=True)
    except OSError as e:
        raise PluginInstallError(
            f"Nie moglem utworzyc folderu: {plugin_dir} ({e})"
        )

    # Jesli plik docelowy juz istnieje z TA SAMA suma - nie trzeba kopiowac,
    # ale sprawdzamy to jawnie (zeby komunikat w oknie byl taki sam jak po
    # swiezym skopiowaniu - punkt 4 zlecenia: "Komunikat: Plugin zainstalowany w: <sciezka>").
    if os.path.isfile(target):
        try:
            existing_sha = sha256_of_file(target)
        except OSError:
            existing_sha = None
        if existing_sha and existing_sha.lower() == expected_sha256.lower():
            return os.path.abspath(target)
        # inna suma (stara wersja) -> podmien

    try:
        shutil.copy2(src, target)
    except OSError as e:
        raise PluginInstallError(
            f"Kopiowanie nie powiodlo sie: {target} ({e}). Sprawdz "
            "uprawnienia do folderu ETS2 (moze wymagac uruchomienia "
            "instalatora jako administrator)."
        )

    if not os.path.isfile(target):
        raise PluginInstallError(
            f"Po kopiowaniu plik nie istnieje w folderze docelowym: {target}"
        )

    actual_sha = sha256_of_file(target)
    if actual_sha.lower() != expected_sha256.lower():
        raise PluginInstallError(
            "SHA-256 skopiowanego pliku nie zgadza sie z oczekiwanym "
            f"(oczekiwano {expected_sha256}, otrzymano {actual_sha}). Plik "
            "moze byc uszkodzony - uruchom instalator ponownie."
        )

    return os.path.abspath(target)
