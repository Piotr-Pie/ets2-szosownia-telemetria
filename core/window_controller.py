#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - logika okna/zasobnika (v0.2.3)
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


class TraySendGate:
    """ETS2 Szosownia v0.2.3 - wariant B autostartu (decyzja wlasciciela
    2026-11-09): logika "kiedy wysylka startuje przy --tray i po menu
    zasobnika", WYDZIELONA z app.py zeby dalo sie przetestowac bez
    prawdziwego tkinter/pystray (ktore nie startuja na tym Linuksie bez
    serwera X - patrz tests/test_tray_send_gate.py).

    `on_start_sending` / `on_stop_sending` odpowiadaja w app.py metodom
    App.on_save_and_start() / App.on_stop() (w testach to atrapa
    zliczajaca wywolania).
    """

    def __init__(self, on_start_sending: Callable[[], None], on_stop_sending: Callable[[], None]):
        self.on_start_sending = on_start_sending
        self.on_stop_sending = on_stop_sending
        self.sending_paused = False

    def start_from_tray(self) -> None:
        """Wywolywane przy starcie z flaga --tray (main() -> App.__init__
        z start_hidden=True). Wariant B: NIGDY nie uruchamia wysylki
        automatycznie (nawet gdy jest zapisany token i znaleziona gra) -
        tylko oznacza stan jako wstrzymany, zeby menu zasobnika od razu
        pokazywalo "Wznów wysyłkę" i jej klikniecie zadzialalo."""
        self.sending_paused = True

    def toggle_from_tray_menu(self) -> None:
        """"Wstrzymaj wysyłkę" / "Wznów wysyłkę" z menu zasobnika."""
        if self.sending_paused:
            self.on_start_sending()
            self.sending_paused = False
        else:
            self.on_stop_sending()
            self.sending_paused = True

    def mark_started(self) -> None:
        """Wywolywane po kliknieciu "Zapisz i uruchom" w oknie (dowolne
        wejscie, nie tylko z menu zasobnika) - synchronizuje stan z
        realnym startem wysylki, zeby menu zasobnika pokazalo "Wstrzymaj
        wysyłkę"."""
        self.sending_paused = False

    def mark_stopped(self) -> None:
        """Wywolywane po kliknieciu "Zatrzymaj" w oknie."""
        self.sending_paused = True
