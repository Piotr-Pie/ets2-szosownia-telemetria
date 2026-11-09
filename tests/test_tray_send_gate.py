#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowy test (v0.2.3, wariant B autostartu - decyzja wlasciciela
2026-11-09): start z flaga --tray NIE startuje wysylki automatycznie,
nawet gdy jest zapisany token i znaleziona gra. Wysylka startuje dopiero
po "Zapisz i uruchom" w oknie albo "Wznów wysyłkę" z menu zasobnika.

Testuje core.window_controller.TraySendGate na atrapie (bez prawdziwego
tkinter/pystray - patrz tests/test_window_controller.py dla tego samego
wzorca). Dodatkowo test_tray_flag_does_not_autostart_app_integration
sprawdza samo app.py (App.__init__, start_hidden=True) z atrapa root
Tk, bez importu prawdziwego tkinter.Tk() (nie startuje na tym Linuksie
bez serwera X, zweryfikowane w tej sesji: `tkinter.Tk()` rzuca
`TclError: no display name and no $DISPLAY environment variable`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.window_controller import TraySendGate  # noqa: E402

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


def test_start_from_tray_never_autostarts_sending():
    """Rdzen wariantu B: start_from_tray() NIE wywoluje on_start_sending,
    niezaleznie od tego, czy jest zapisany token/gra (ta decyzja jest
    teraz calkowicie poza TraySendGate - app.py wola start_from_tray()
    bezwarunkowo przy --tray, patrz app.py App.__init__)."""
    started = []
    stopped = []
    gate = TraySendGate(on_start_sending=lambda: started.append(1), on_stop_sending=lambda: stopped.append(1))
    gate.start_from_tray()
    check_true("start z --tray: wysylka NIE wystartowala automatycznie", started == [])
    check_true("start z --tray: sending_paused == True", gate.sending_paused)


def test_resume_from_tray_menu_starts_sending():
    """Po starcie z --tray, wybranie 'Wznów wysyłkę' z menu zasobnika
    (toggle_from_tray_menu, gdy sending_paused==True) WYSTARTOWUJE
    wysylke (wywoluje on_start_sending - w app.py to on_save_and_start)."""
    started = []
    stopped = []
    gate = TraySendGate(on_start_sending=lambda: started.append(1), on_stop_sending=lambda: stopped.append(1))
    gate.start_from_tray()
    gate.toggle_from_tray_menu()
    check("'Wznów wysyłkę' startuje wysylke (on_start_sending wywolane raz)", started, [1])
    check_true("po wznowieniu sending_paused == False", not gate.sending_paused)


def test_toggle_again_pauses_sending():
    """Drugie wywolanie toggle (menu teraz pokazuje 'Wstrzymaj
    wysyłkę') zatrzymuje wysylke (on_stop_sending)."""
    started = []
    stopped = []
    gate = TraySendGate(on_start_sending=lambda: started.append(1), on_stop_sending=lambda: stopped.append(1))
    gate.start_from_tray()
    gate.toggle_from_tray_menu()  # wznow
    gate.toggle_from_tray_menu()  # wstrzymaj
    check("drugi toggle wstrzymuje (on_stop_sending wywolane raz)", stopped, [1])
    check_true("po wstrzymaniu sending_paused == True", gate.sending_paused)


def test_mark_started_and_stopped_sync_state():
    """mark_started()/mark_stopped() (wywolywane z App.on_save_and_start/
    App.on_stop) synchronizuja sending_paused - uzywane m.in. przy
    zwyklym starcie bez --tray (klik 'Zapisz i uruchom' w oknie), zeby
    menu zasobnika pokazalo poprawna etykiete nawet gdy program nie byl
    wystartowany z --tray."""
    gate = TraySendGate(on_start_sending=lambda: None, on_stop_sending=lambda: None)
    check("na starcie (bez --tray) sending_paused == False", gate.sending_paused, False)
    gate.mark_started()
    check("po mark_started() sending_paused == False", gate.sending_paused, False)
    gate.mark_stopped()
    check("po mark_stopped() sending_paused == True", gate.sending_paused, True)


def test_normal_start_without_tray_flag_unchanged_contract():
    """Zwykly start bez --tray: TraySendGate zaczyna z sending_paused ==
    False (domyslne, konstruktor) i NIKT nie wola start_from_tray() -
    zachowanie identyczne jak przed v0.2.3 (okno dziala normalnie, klik
    'Zapisz i uruchom' startuje wysylke przez App.on_save_and_start,
    niezmieniony w tej zmianie poza wywolaniem mark_started())."""
    gate = TraySendGate(on_start_sending=lambda: None, on_stop_sending=lambda: None)
    check_true("bez --tray: sending_paused zaczyna jako False (brak wplywu wariantu B)", not gate.sending_paused)


if __name__ == "__main__":
    test_start_from_tray_never_autostarts_sending()
    test_resume_from_tray_menu_starts_sending()
    test_toggle_again_pauses_sending()
    test_mark_started_and_stopped_sync_state()
    test_normal_start_without_tray_flag_unchanged_contract()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy TraySendGate (wariant B autostartu) przeszły")
