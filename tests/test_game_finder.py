#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowe testy (v0.2.0): wyszukiwanie gry (core.game_finder).

Pokrywa: parsowanie libraryfolders.vdf (podwojne backslashe, wiele
bibliotek na roznych dyskach, duplikaty, brak kluczy, koncowy backslash),
normalizacje recznie podanej/wybranej sciezki, is_valid_game_root na
prawdziwych katalogach tymczasowych (bez rejestru Windows).

ZASTRZEZENIE: get_steam_paths_from_registry() (winreg) NIE jest
testowane tutaj - ten host (Linux) nie ma winreg. Test nizej sprawdza
tylko, ze funkcja nie wywala sie i zwraca liste (pusta, bo winreg=None na
Linuksie) - patrz raport."""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import game_finder  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


# ---------------------------------------------------------------------------
# parse_vdf_library_paths
# ---------------------------------------------------------------------------

def test_vdf_single_library_double_backslash():
    content = (
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        '\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n'
        '\t\t"label"\t\t""\n'
        "\t}\n"
        "}\n"
    )
    libs = game_finder.parse_vdf_library_paths(content)
    check("1 biblioteka, podwojny backslash", libs, ["C:\\Program Files (x86)\\Steam"])


def test_vdf_multiple_libraries_other_drives():
    content = (
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        '\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n'
        "\t}\n"
        '\t"1"\n'
        "\t{\n"
        '\t\t"path"\t\t"F:\\\\SteamLibrary"\n'
        "\t}\n"
        '\t"2"\n'
        "\t{\n"
        '\t\t"path"\t\t"D:\\\\Games\\\\SteamLibrary2"\n'
        "\t}\n"
        "}\n"
    )
    libs = game_finder.parse_vdf_library_paths(content)
    check(
        "3 biblioteki, rozne dyski",
        libs,
        [
            "C:\\Program Files (x86)\\Steam",
            "F:\\SteamLibrary",
            "D:\\Games\\SteamLibrary2",
        ],
    )


def test_vdf_duplicate_paths_deduplicated():
    content = (
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"F:\\\\SteamLibrary"\n\t}\n'
        '\t"1"\n\t{\n\t\t"path"\t\t"F:\\\\SteamLibrary"\n\t}\n}\n'
    )
    libs = game_finder.parse_vdf_library_paths(content)
    check("duplikaty wywalone", libs, ["F:\\SteamLibrary"])


def test_vdf_no_path_keys_returns_empty():
    content = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"label"\t\t""\n\t}\n}\n'
    libs = game_finder.parse_vdf_library_paths(content)
    check("brak kluczy path -> lista pusta", libs, [])


def test_vdf_trailing_backslash_stripped():
    content = '"path"\t\t"F:\\\\SteamLibrary\\\\"\n'
    libs = game_finder.parse_vdf_library_paths(content)
    check("koncowy backslash obciety", libs, ["F:\\SteamLibrary"])


# ---------------------------------------------------------------------------
# normalize_game_path_input
# ---------------------------------------------------------------------------

ROOT = "F:\\SteamLibrary\\steamapps\\common\\Euro Truck Simulator 2"


def test_normalize_root_folder_passthrough():
    check("folder gry bez zmian", game_finder.normalize_game_path_input(ROOT), ROOT)


def test_normalize_root_folder_quoted():
    check("folder gry w cudzyslowach", game_finder.normalize_game_path_input(f'"{ROOT}"'), ROOT)


def test_normalize_bin_win_x64():
    check("sciezka do bin\\win_x64", game_finder.normalize_game_path_input(ROOT + "\\bin\\win_x64"), ROOT)


def test_normalize_exe_file():
    check(
        "sciezka do eurotrucks2.exe",
        game_finder.normalize_game_path_input(ROOT + "\\bin\\win_x64\\eurotrucks2.exe"),
        ROOT,
    )


def test_normalize_exe_file_uppercase_and_trailing_space():
    check(
        "exe wielkimi literami + spacja na koncu",
        game_finder.normalize_game_path_input(ROOT + "\\bin\\win_x64\\EuroTrucks2.EXE  "),
        ROOT,
    )


def test_normalize_forward_slashes():
    unix_style = ROOT.replace("\\", "/")
    check("ukosniki zwykle (/) zamiast backslash", game_finder.normalize_game_path_input(unix_style), ROOT)


def test_normalize_trailing_backslash():
    check("koncowy backslash obciety", game_finder.normalize_game_path_input(ROOT + "\\"), ROOT)


def test_normalize_empty_returns_none():
    check("puste wejscie -> None", game_finder.normalize_game_path_input(""), None)
    check("same spacje -> None", game_finder.normalize_game_path_input("   "), None)
    check("None -> None", game_finder.normalize_game_path_input(None), None)


# ---------------------------------------------------------------------------
# is_valid_game_root - prawdziwe katalogi tymczasowe (bez rejestru)
# ---------------------------------------------------------------------------

def test_is_valid_game_root_detects_real_exe():
    tmpdir = tempfile.mkdtemp(prefix="ets2-gamefinder-test-")
    try:
        game_dir = os.path.join(tmpdir, "Euro Truck Simulator 2")
        bin_dir = os.path.join(game_dir, "bin", "win_x64")
        os.makedirs(bin_dir)
        exe_path = os.path.join(bin_dir, "eurotrucks2.exe")
        with open(exe_path, "wb") as f:
            f.write(b"MZ-fake-exe")

        result = game_finder.is_valid_game_root(game_dir)
        check("exe istnieje -> folder uznany za poprawny", result, os.path.abspath(game_dir))

        missing = os.path.join(tmpdir, "Nie Istnieje")
        result2 = game_finder.is_valid_game_root(missing)
        check("folder bez exe -> None", result2, None)

        result3 = game_finder.is_valid_game_root(None)
        check("None -> None", result3, None)

        result4 = game_finder.is_valid_game_root("")
        check("pusty string -> None", result4, None)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_get_steam_library_paths_reads_vdf_from_disk():
    tmpdir = tempfile.mkdtemp(prefix="ets2-gamefinder-vdf-test-")
    try:
        steam_dir = os.path.join(tmpdir, "Steam")
        steamapps_dir = os.path.join(steam_dir, "steamapps")
        os.makedirs(steamapps_dir)
        vdf_path = os.path.join(steamapps_dir, "libraryfolders.vdf")
        with open(vdf_path, "w", encoding="utf-8") as f:
            f.write('"path"\t\t"F:\\\\SteamLibrary"\n')

        libs = game_finder.get_steam_library_paths(steam_dir)
        check("steam_dir + biblioteka z vdf (2 wpisy)", libs, [steam_dir, "F:\\SteamLibrary"])

        libs_missing_vdf = game_finder.get_steam_library_paths(os.path.join(tmpdir, "InnySteam"))
        check("brak vdf -> tylko sama sciezka steam", libs_missing_vdf, [os.path.join(tmpdir, "InnySteam")])

        check("pusta sciezka -> pusta lista", game_finder.get_steam_library_paths(""), [])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_registry_lookup_does_not_crash_without_winreg():
    """Na Linuksie (brak winreg) funkcja NIE MOZE wywalic sie - musi
    zwrocic liste (pusta). Nie testuje rejestru Windows (patrz raport)."""
    try:
        result = game_finder.get_steam_paths_from_registry()
        ok = isinstance(result, list)
    except Exception as e:  # pragma: no cover - nie powinno sie zdarzyc
        ok = False
        print(f"[FAIL] wyjatek: {e}")
    check("get_steam_paths_from_registry() zwraca liste bez wyjatku", ok, True)


def test_find_game_root_returns_none_and_checked_list_when_nothing_found():
    """Na tym hoscie (brak Steam/winreg) find_game_root() powinien zwrocic
    None + niepusta liste sprawdzonych lokalizacji (do pokazania w GUI)."""
    root, checked = game_finder.find_game_root()
    check("brak gry na tym hoscie -> root=None", root, None)
    check("lista sprawdzonych lokalizacji niepusta", len(checked) > 0, True)


if __name__ == "__main__":
    test_vdf_single_library_double_backslash()
    test_vdf_multiple_libraries_other_drives()
    test_vdf_duplicate_paths_deduplicated()
    test_vdf_no_path_keys_returns_empty()
    test_vdf_trailing_backslash_stripped()
    test_normalize_root_folder_passthrough()
    test_normalize_root_folder_quoted()
    test_normalize_bin_win_x64()
    test_normalize_exe_file()
    test_normalize_exe_file_uppercase_and_trailing_space()
    test_normalize_forward_slashes()
    test_normalize_trailing_backslash()
    test_normalize_empty_returns_none()
    test_is_valid_game_root_detects_real_exe()
    test_get_steam_library_paths_reads_vdf_from_disk()
    test_registry_lookup_does_not_crash_without_winreg()
    test_find_game_root_returns_none_and_checked_list_when_nothing_found()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy wyszukiwania gry (core.game_finder) przeszły")
