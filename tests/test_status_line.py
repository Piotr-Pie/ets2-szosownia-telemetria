#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test linii statusu (port z client/tests/test_status_line.py v0.1.3,
import dostosowany do core.ets2_core - logika BEZ ZMIAN)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import status_line  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = got == want
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def test_status_line_text():
    check(
        "gra nie dziala",
        status_line(running=False, connected=False),
        "[status] gra nie jest uruchomiona",
    )
    check(
        "gra dziala, SCS niedostepna",
        status_line(running=True, connected=False),
        "[status] gra działa, pamięć SCS: niedostępna "
        "(sprawdź plugin w bin\\win_x64\\plugins)",
    )
    check(
        "gra dziala, SCS dostepna",
        status_line(running=True, connected=True),
        "[status] gra działa, pamięć SCS: dostępna",
    )


def test_status_line_no_token_leak():
    import inspect

    sig = inspect.signature(status_line)
    params = list(sig.parameters.keys())
    check("status_line() parametry", params, ["running", "connected"])


def simulate_main_loop_prints(sequence):
    last_state = None
    printed = []
    for running, connected in sequence:
        state = (running, connected)
        if state != last_state:
            last_state = state
            printed.append(status_line(running, connected))
    return printed


def test_status_printed_once_not_every_tick():
    sequence = [(True, False)] * 5
    printed = simulate_main_loop_prints(sequence)
    check("liczba linii (5x ten sam stan)", len(printed), 1)
    check("tresc jedynej linii", printed[0], status_line(True, False))


def test_status_printed_on_each_transition():
    sequence = [
        (False, False),
        (True, False),
        (True, False),
        (True, True),
        (True, False),
    ]
    printed = simulate_main_loop_prints(sequence)
    check("liczba wypisanych linii", len(printed), 4)
    check(
        "kolejnosc linii",
        printed,
        [
            status_line(False, False),
            status_line(True, False),
            status_line(True, True),
            status_line(True, False),
        ],
    )


def test_status_line_never_contains_placeholder_token():
    forbidden = ["token", "server_url", "tls_sha256_pin"]
    lines = [
        status_line(False, False),
        status_line(True, False),
        status_line(True, True),
    ]
    all_ok = True
    for f in forbidden:
        for line in lines:
            if f in line:
                all_ok = False
    check("brak nazw pol config.json w liniach statusu", all_ok, True)


if __name__ == "__main__":
    test_status_line_text()
    test_status_line_no_token_leak()
    test_status_printed_once_not_every_tick()
    test_status_printed_on_each_transition()
    test_status_line_never_contains_placeholder_token()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy linii statusu (core.ets2_core) przeszły")
