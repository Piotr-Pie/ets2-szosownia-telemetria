#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test logiki 'X = chowaj do zasobnika, Zakończ = zamknij naprawdę' na
atrapie okna (v0.2.2) - bez prawdziwego tkinter.Tk() (nie startuje na
Linuksie bez X)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.window_controller import TrayWindowController  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


class FakeWindow:
    def __init__(self):
        self.calls = []

    def withdraw(self):
        self.calls.append("withdraw")

    def deiconify(self):
        self.calls.append("deiconify")

    def lift(self):
        self.calls.append("lift")

    def destroy(self):
        self.calls.append("destroy")


def test_close_button_hides_when_tray_available():
    win = FakeWindow()
    stopped = []
    ctrl = TrayWindowController(win, tray_available=True, on_stop_sending=lambda: stopped.append(1))
    ctrl.on_window_close_button()
    check("X z zasobnikiem: withdraw wywolane", win.calls, ["withdraw"])
    check("X z zasobnikiem: okno NIE zamknięte (visible flag)", ctrl.closed, False)
    check("X z zasobnikiem: wysylka NIE zatrzymana", stopped, [])


def test_close_button_quits_when_tray_unavailable():
    win = FakeWindow()
    stopped = []
    ctrl = TrayWindowController(win, tray_available=False, on_stop_sending=lambda: stopped.append(1))
    ctrl.on_window_close_button()
    check("X bez zasobnika: destroy wywolane", win.calls, ["destroy"])
    check("X bez zasobnika: wysylka zatrzymana", stopped, [1])
    check("X bez zasobnika: ctrl.closed == True", ctrl.closed, True)


def test_tray_show_deiconifies_and_lifts():
    win = FakeWindow()
    ctrl = TrayWindowController(win, tray_available=True, on_stop_sending=lambda: None)
    ctrl.hide()
    win.calls.clear()
    ctrl.show()
    check("show(): deiconify + lift", win.calls, ["deiconify", "lift"])
    check("visible == True po show()", ctrl.visible, True)


def test_toggle_visibility():
    win = FakeWindow()
    ctrl = TrayWindowController(win, tray_available=True, on_stop_sending=lambda: None)
    check("na starcie widoczne", ctrl.visible, True)
    ctrl.toggle_visibility()
    check("po 1. toggle: schowane", ctrl.visible, False)
    check("1. toggle wywolalo withdraw", win.calls[-1], "withdraw")
    ctrl.toggle_visibility()
    check("po 2. toggle: widoczne", ctrl.visible, True)
    check("2. toggle wywolalo deiconify", win.calls[-1] in ("deiconify", "lift"), True)


def test_quit_from_tray_menu_stops_sending_and_destroys():
    win = FakeWindow()
    stopped = []
    ctrl = TrayWindowController(win, tray_available=True, on_stop_sending=lambda: stopped.append(1))
    ctrl.quit()
    check("Zakończ z menu: wysylka zatrzymana", stopped, [1])
    check("Zakończ z menu: destroy wywolane", "destroy" in win.calls, True)
    check("Zakończ z menu: ctrl.closed == True", ctrl.closed, True)


def test_quit_is_idempotent():
    win = FakeWindow()
    stopped = []
    ctrl = TrayWindowController(win, tray_available=True, on_stop_sending=lambda: stopped.append(1))
    ctrl.quit()
    ctrl.quit()
    check("quit() wywolane dwukrotnie: on_stop_sending tylko raz", len(stopped), 1)
    check("quit() wywolane dwukrotnie: destroy tylko raz", win.calls.count("destroy"), 1)


if __name__ == "__main__":
    test_close_button_hides_when_tray_available()
    test_close_button_quits_when_tray_unavailable()
    test_tray_show_deiconifies_and_lifts()
    test_toggle_visibility()
    test_quit_from_tray_menu_stops_sending_and_destroys()
    test_quit_is_idempotent()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy logiki okno/zasobnik (atrapa okna) przeszły")
