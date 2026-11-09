#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test importu pystray/Pillow + budowy obrazu ikony zasobnika (v0.2.2).
NIE uruchamia prawdziwego zasobnika (pystray.Icon.run()) - patrz raport.

UWAGA WAZNA (znalezisko tej sesji, patrz raport): `import pystray` na
Linuksie bez serwera X (ten kontener, brak zmiennej $DISPLAY) rzuca
Xlib.error.DisplayNameError - NIE ImportError - bo pystray przy imporcie
EAGERLY wybiera backend (Xorg na Linuksie) i od razu laczy sie z serwerem
X. To jest zachowanie samej biblioteki pystray, nie bledu w tym kodzie,
ale oznacza, ze app.py NIE MOZE lapac tylko ImportError przy wlaczaniu
zasobnika - musi lapac szeroki Exception (patrz app.py, TRAY_AVAILABLE).
Na produkcyjnym Windows pystray uzywa backendu win32 (nie Xorg) i ten
problem nie wystepuje - NIE TESTOWANE na prawdziwym Windows w tej sesji."""
import importlib.util
import os
import site
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pystray zostal zainstalowany w tej sesji z `pip3 install --user` (patrz
# raport), a ten venv ma site.ENABLE_USER_SITE == False, wiec user-site
# trzeba dodac recznie, zeby test dzialal bez dodatkowych zmiennych srodowiskowych.
_user_site = site.getusersitepackages()
if _user_site not in sys.path and os.path.isdir(_user_site):
    sys.path.append(_user_site)

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


def test_pillow_imports_cleanly():
    try:
        import PIL  # noqa: F401
        print("[OK ] import PIL (Pillow) powiodl sie")
    except ImportError as e:
        global FAIL
        FAIL += 1
        print(f"[FAIL] import PIL nie powiodl sie: {e!r}")


def test_pystray_package_is_installed():
    """Sprawdza, ze pakiet pystray jest zainstalowany (find_spec), bez
    wykonywania pystray/__init__.py (ktory na Linuksie bez X wybiera
    backend Xorg i laczy sie z serwerem X - patrz test nizej)."""
    spec = importlib.util.find_spec("pystray")
    check_true("pystray jest zainstalowany (importlib.util.find_spec)", spec is not None)


def test_pystray_import_on_headless_linux_documented():
    """Dokumentuje realny wynik `import pystray` w TYM srodowisku
    (headless, bez $DISPLAY). Nie jest to FAIL - to oczekiwane zachowanie
    pystray na Linuksie bez X, zaadresowane w app.py szerokim except."""
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        print("[SKIP] test specyficzny dla headless Linux bez $DISPLAY")
        return
    try:
        import pystray  # noqa: F401
        print("[OK ] import pystray powiodl sie (serwer X byl dostepny)")
    except Exception as e:  # noqa: BLE001 - dokumentujemy KAZDY wyjatek
        print(
            f"[INFO] import pystray rzucil {type(e).__name__}: {e} "
            "- oczekiwane na headless Linuksie bez $DISPLAY, patrz raport. "
            "app.py musi lapac Exception (nie tylko ImportError) wokol tego importu."
        )


def test_build_icon_image_basic_properties():
    from core.tray_icon import build_icon_image
    from PIL import Image

    img = build_icon_image(size=64)
    check_true("build_icon_image() zwraca PIL.Image", isinstance(img, Image.Image))
    check("rozmiar obrazu 64x64", img.size, (64, 64))
    check("tryb RGBA", img.mode, "RGBA")


def test_build_icon_image_different_sizes_do_not_raise():
    from core.tray_icon import build_icon_image

    ok = True
    for size in (16, 32, 48, 128):
        try:
            img = build_icon_image(size=size)
            if img.size != (size, size):
                ok = False
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[FAIL] build_icon_image({size}) rzucilo: {e!r}")
    check_true("build_icon_image() dziala dla kilku rozmiarow", ok)


def test_icon_colors_match_visual_system_no_logo():
    """Sprawdza, ze uzyte kolory sa TYMI z systemu wizualnego (#5cbfae /
    #0e1522), nie placeholderem/domyslnym Pillow. Brak logotypow SCS/Steam
    jest weryfikacja wizualna poza zakresem testu automatycznego - patrz
    raport."""
    from core import tray_icon

    check("kolor tla", tray_icon.COLOR_BG.lower(), "#0e1522")
    check("kolor rysunku", tray_icon.COLOR_FG.lower(), "#5cbfae")


def test_pystray_icon_object_construction_if_backend_available():
    """Konstruktor pystray.Icon (bez .run()/.run_detached()) - tylko gdy
    import pystray sie powiodl w tym srodowisku (patrz test wyzej).
    Inaczej SKIP (bez X nie da sie zweryfikowac na tym hoscie - NIE
    TESTOWANE, patrz raport; dziala na Windows, backend win32)."""
    try:
        import pystray
    except Exception as e:  # noqa: BLE001
        print(
            f"[SKIP] pystray.Icon() nie przetestowane - import pystray "
            f"rzucil {type(e).__name__} w tym srodowisku (brak $DISPLAY)"
        )
        return
    from core.tray_icon import build_icon_image

    menu = pystray.Menu(
        pystray.MenuItem("Pokaż okno", lambda: None, default=True),
        pystray.MenuItem("Wstrzymaj wysyłkę", lambda: None),
        pystray.MenuItem("Zakończ", lambda: None),
    )
    icon = pystray.Icon("ets2szosownia", build_icon_image(), "status testowy", menu=menu)
    check_true("pystray.Icon() skonstruowany bez wyjatku", icon is not None)


if __name__ == "__main__":
    test_pillow_imports_cleanly()
    test_pystray_package_is_installed()
    test_pystray_import_on_headless_linux_documented()
    test_build_icon_image_basic_properties()
    test_build_icon_image_different_sizes_do_not_raise()
    test_icon_colors_match_visual_system_no_logo()
    test_pystray_icon_object_construction_if_backend_available()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy ikony zasobnika (import + budowa obrazu) przeszły")
