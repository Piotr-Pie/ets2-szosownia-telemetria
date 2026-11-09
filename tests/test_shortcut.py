#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy skrotu na pulpicie (v0.2.2): budowa komendy PowerShell bez
wstrzykiwania (zmienne srodowiskowe, nie string concat) + wybor katalogu
pulpitu (USERPROFILE / OneDrive). Prawdziwy subprocess.run NIE jest
wolany - wstrzykujemy atrape `runner` (patrz raport: brak testu na
prawdziwym PowerShell/Windows)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import shortcut  # noqa: E402

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


class FakeCompletedProcess:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def test_desktop_dir_plain_userprofile():
    tmpdir = tempfile.mkdtemp(prefix="ets2-desktop-test-")
    try:
        env = {"USERPROFILE": tmpdir}
        result = shortcut.get_desktop_dir(env=env)
        check("katalog pulpitu bez OneDrive", result, os.path.join(tmpdir, "Desktop"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_desktop_dir_prefers_onedrive_when_present():
    tmpdir = tempfile.mkdtemp(prefix="ets2-desktop-test-")
    try:
        onedrive_desktop = os.path.join(tmpdir, "OneDrive", "Desktop")
        os.makedirs(onedrive_desktop)
        env = {"USERPROFILE": tmpdir}
        result = shortcut.get_desktop_dir(env=env)
        check("OneDrive\\Desktop ma priorytet, gdy istnieje", result, onedrive_desktop)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_desktop_dir_missing_userprofile_returns_none():
    result = shortcut.get_desktop_dir(env={})
    check("brak USERPROFILE -> None", result, None)


def test_command_never_embeds_path_as_string_concat():
    """Sciezka docelowa NIE trafia do listy argumentow subprocess - tylko
    do zmiennych srodowiskowych. To jest WLASNIE mechanizm "bez
    wstrzykiwania" wymagany przez zlecenie."""
    tricky_path = r"C:\Users\Gracz O'Brien\Pulpit app's\ETS2 Szosownia - Telemetria v0.2.2.exe"
    captured = {}

    def fake_runner(args, env, capture_output, text, timeout, **kwargs):
        captured["args"] = args
        captured["env"] = env
        return FakeCompletedProcess(returncode=0)

    tmpdir = tempfile.mkdtemp(prefix="ets2-shortcut-test-")
    try:
        result_path = shortcut.create_desktop_shortcut(
            tricky_path, desktop_dir=tmpdir, runner=fake_runner
        )
        check(
            "sciezka docelowa zwrocona jako sciezka skrotu",
            result_path,
            os.path.join(tmpdir, shortcut.SHORTCUT_FILE_NAME),
        )
        args_joined = " ".join(captured["args"])
        check_true(
            "sciezka z apostrofem/spacjami NIE jest w argumentach komendy",
            tricky_path not in args_joined,
        )
        check(
            "ETS2_SHORTCUT_TARGET w env == dokladna sciezka (bez modyfikacji)",
            captured["env"]["ETS2_SHORTCUT_TARGET"],
            tricky_path,
        )
        check(
            "skrypt PowerShell jest stalym tekstem (bez interpolacji sciezki)",
            tricky_path not in shortcut._SHORTCUT_SCRIPT,
            True,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_powershell_error_raises_shortcut_error_with_detail():
    def failing_runner(args, env, capture_output, text, timeout, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr="Com object nie znaleziony")

    tmpdir = tempfile.mkdtemp(prefix="ets2-shortcut-test-")
    try:
        try:
            shortcut.create_desktop_shortcut(
                r"C:\app.exe", desktop_dir=tmpdir, runner=failing_runner
            )
            global FAIL
            FAIL += 1
            print("[FAIL] oczekiwano ShortcutError przy returncode != 0")
        except shortcut.ShortcutError as e:
            check_true("komunikat bledu zawiera detal z PowerShell", "Com object" in str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_missing_desktop_dir_raises_shortcut_error():
    global FAIL
    try:
        shortcut.create_desktop_shortcut(r"C:\app.exe", desktop_dir=None, runner=lambda **k: None)
        # desktop_dir=None powoduje wywolanie get_desktop_dir() prawdziwego -
        # na tym hoscie Linux USERPROFILE zwykle nie istnieje -> ShortcutError
        FAIL += 1
        print("[FAIL] oczekiwano ShortcutError, gdy brak katalogu pulpitu")
    except shortcut.ShortcutError:
        print("[OK ] brak USERPROFILE -> ShortcutError (zgodnie z oczekiwaniem)")
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"[FAIL] nieoczekiwany wyjatek: {e!r}")


if __name__ == "__main__":
    test_desktop_dir_plain_userprofile()
    test_desktop_dir_prefers_onedrive_when_present()
    test_desktop_dir_missing_userprofile_returns_none()
    test_command_never_embeds_path_as_string_concat()
    test_powershell_error_raises_shortcut_error_with_detail()
    if "USERPROFILE" not in os.environ:
        test_missing_desktop_dir_raises_shortcut_error()
    else:
        print("[SKIP] test_missing_desktop_dir_raises_shortcut_error (USERPROFILE ustawione w tym środowisku)")
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy skrotu na pulpicie (atrapa runner) przeszły")
