#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - logika okna/zasobnika (v0.2.2)
==================================================

NOWY KOD. Czysta logika decyzyjna "zamkniecie okna (X) chowa do zasobnika,
Zakoncz z menu naprawde zamyka program" - WYDZIELONA z tkinter, zeby dalo
sie ja przetestowac na atrapie okna (bez prawdziwego Tk(), ktory nie
startuje na Linuksie bez X - patrz tests/test_window_controller.py).

`window` to kazdy obiekt z metodami withdraw()/deiconify()/destroy() -
w produkcji to prawdziwy tkinter.Tk() (root), w testach to atrapa
rejestrujaca wywolania.
"""

from __future__ import annotations

from typing import Callable


class TrayWindowController:
    def __init__(self, window, tray_available: bool, on_stop_sending: Callable[[], None]):
        self.window = window
        self.tray_available = tray_available
        self.on_stop_sending = on_stop_sending
        self.visible = True
        self.closed = False

    def on_window_close_button(self) -> None:
        """WM_DELETE_WINDOW (klik na X): chowa do zasobnika, gdy zasobnik
        dziala; inaczej zamyka program calkowicie (zachowanie z v0.2.1,
        zeby program nie zostal "w tle bez sposobu na zamkniecie", gdy
        pystray/Pillow sa niedostepne)."""
        if self.tray_available:
            self.hide()
        else:
            self.quit()

    def hide(self) -> None:
        self.window.withdraw()
        self.visible = False

    def show(self) -> None:
        self.window.deiconify()
        try:
            self.window.lift()
        except AttributeError:
            pass
        self.visible = True

    def toggle_visibility(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def quit(self) -> None:
        """Zakoncz z menu zasobnika (albo X, gdy zasobnik niedostepny):
        zatrzymuje wysylke I zamyka program."""
        if not self.closed:
            self.on_stop_sending()
            self.window.destroy()
            self.closed = True
