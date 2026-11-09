#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy poprawki kernel32 (port z client/tests/test_kernel32_winapi.py
v0.1.3, import dostosowany do core.ets2_core - logika BEZ ZMIAN).

ZASTRZEZENIE: ten host (Linux) NIE MA prawdziwego kernel32.dll - testy
nizej NIE wywoluja zadnej prawdziwej funkcji WinAPI (patrz komentarze w
kazdym tescie)."""
import sys
import os
import ctypes as C

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.ets2_core as ets2_core  # noqa: E402
from core.ets2_core import (  # noqa: E402
    _configure_kernel32,
    _PROCESSENTRY32,
    safe_read_memory,
    safe_parse_telemetry,
    mem_error_status_line,
)

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


class _FakeWinapiFunc:
    def __init__(self):
        self.argtypes = None
        self.restype = None


class _FakeKernel32:
    FUNC_NAMES = (
        "OpenFileMappingW",
        "MapViewOfFile",
        "UnmapViewOfFile",
        "CloseHandle",
        "CreateToolhelp32Snapshot",
        "Process32First",
        "Process32Next",
    )

    def __init__(self):
        for name in self.FUNC_NAMES:
            setattr(self, name, _FakeWinapiFunc())


def test_configure_sets_argtypes_and_restype_for_every_function():
    fake = _FakeKernel32()
    _configure_kernel32(fake)

    expected_restype = {
        "OpenFileMappingW": C.c_void_p,
        "MapViewOfFile": C.c_void_p,
        "UnmapViewOfFile": C.c_int,
        "CloseHandle": C.c_int,
        "CreateToolhelp32Snapshot": C.c_void_p,
        "Process32First": C.c_int,
        "Process32Next": C.c_int,
    }
    for name, expected in expected_restype.items():
        func = getattr(fake, name)
        check(f"{name}.restype", func.restype, expected)
        check_true(f"{name}.argtypes ustawione (nie None)", func.argtypes is not None)

    check("UnmapViewOfFile.argtypes", tuple(fake.UnmapViewOfFile.argtypes), (C.c_void_p,))
    check("CloseHandle.argtypes", tuple(fake.CloseHandle.argtypes), (C.c_void_p,))
    check(
        "MapViewOfFile.argtypes",
        tuple(fake.MapViewOfFile.argtypes),
        (C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_size_t),
    )
    check(
        "OpenFileMappingW.argtypes",
        tuple(fake.OpenFileMappingW.argtypes),
        (C.c_uint32, C.c_int, C.c_wchar_p),
    )
    check(
        "Process32First.argtypes",
        tuple(fake.Process32First.argtypes),
        (C.c_void_p, C.POINTER(_PROCESSENTRY32)),
    )


def test_configure_is_idempotent_per_object():
    fake = _FakeKernel32()
    check_true("flaga nieobecna przed konfiguracja", not getattr(fake, "_ets2_winapi_configured", False))
    _configure_kernel32(fake)
    check_true("flaga ustawiona po konfiguracji", getattr(fake, "_ets2_winapi_configured", False))
    fake.UnmapViewOfFile.restype = "ZMIENIONE_RECZNIE"
    _configure_kernel32(fake)
    check("drugie wywolanie nie nadpisuje (no-op po fladze)", fake.UnmapViewOfFile.restype, "ZMIENIONE_RECZNIE")


def test_64bit_address_fits_c_void_p_without_overflow():
    addr = 0x00007FF612340000
    check_true("adres > 2**31 (powyzej zakresu 32-bit signed int)", addr > 2**31)
    converted = C.c_void_p(addr)
    check("c_void_p zachowuje adres bez zmian", converted.value, addr)


def test_default_ctypes_int_conversion_can_overflow_argumenterror():
    libc = C.CDLL(None)
    huge_value = 2 ** 100
    try:
        libc.strlen(huge_value)
        print("[FAIL] oczekiwano ArgumentError/OverflowError dla ogromnej wartosci")
        global FAIL
        FAIL += 1
    except C.ArgumentError as e:
        msg = str(e)
        check_true("komunikat zawiera 'OverflowError'", "OverflowError" in msg)
        check_true("komunikat zawiera 'int too long to convert'", "int too long to convert" in msg)
        print(f"[OK ] ArgumentError odtworzony (mechanizm identyczny jak w zgloszeniu): {msg}")


def test_invalid_handle_value_matches_c_void_p_restype():
    check_true(
        "INVALID_HANDLE_VALUE to duza liczba dodatnia (c_void_p(-1).value)",
        ets2_core.INVALID_HANDLE_VALUE is not None and ets2_core.INVALID_HANDLE_VALUE > 0,
    )
    check("INVALID_HANDLE_VALUE == c_void_p(-1).value", ets2_core.INVALID_HANDLE_VALUE, C.c_void_p(-1).value)


class _SequenceReader:
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    def read(self):
        self.calls += 1
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior


def simulate_resilient_loop(reader, iterations):
    printed = []
    last_mem_error = None
    recovered_iterations = 0
    for _ in range(iterations):
        raw, mem_err = safe_read_memory(reader)
        parsed = None
        if mem_err is None and raw is not None:
            parsed, mem_err = safe_parse_telemetry(raw)
            if mem_err is not None:
                raw = None

        if mem_err is not None:
            if mem_err != last_mem_error:
                last_mem_error = mem_err
                printed.append(mem_error_status_line(mem_err))
        else:
            last_mem_error = None
            if raw is not None:
                recovered_iterations += 1
    return printed, recovered_iterations


def test_single_read_error_then_recovery_prints_one_line():
    good_buf = b"\x00" * ets2_core.MMF_SIZE
    reader = _SequenceReader([OSError("MapViewOfFile zwrocilo blad"), good_buf, good_buf])
    printed, recovered = simulate_resilient_loop(reader, iterations=3)
    check("liczba linii bledu (1 blad -> 1 linia)", len(printed), 1)
    check_true("linia bledu zawiera prefiks [status]", printed[0].startswith("[status] błąd odczytu pamięci SCS:"))
    check_true("linia bledu zawiera 'ponawiam'", "ponawiam" in printed[0])
    check("petla wraca do normalnego odczytu (2 udane odczyty)", recovered, 2)
    check("reader.read() wywolane 3 razy (petla nie przerwala sie)", reader.calls, 3)


def test_ctypes_argument_error_is_caught_too():
    err = C.ArgumentError("argument 1: OverflowError: int too long to convert")
    reader = _SequenceReader([err, b"\x00" * ets2_core.MMF_SIZE])
    printed, recovered = simulate_resilient_loop(reader, iterations=2)
    check("ctypes.ArgumentError zlapany -> 1 linia bledu, bez wyjatku", len(printed), 1)
    check("petla kontynuuje po ArgumentError", recovered, 1)


def test_repeated_identical_error_does_not_spam():
    reader = _SequenceReader([OSError("ciagly blad pamieci")] * 5)
    printed, recovered = simulate_resilient_loop(reader, iterations=5)
    check("5x ten sam blad -> 1 linia", len(printed), 1)
    check("0 udanych odczytow (caly czas blad)", recovered, 0)


def test_error_message_changes_prints_new_line():
    good_buf = b"\x00" * ets2_core.MMF_SIZE
    reader = _SequenceReader([
        OSError("blad A"),
        OSError("blad A"),
        OSError("blad B"),
        good_buf,
        OSError("blad A"),
    ])
    printed, recovered = simulate_resilient_loop(reader, iterations=5)
    check("liczba linii (A, B, A-po-sukcesie)", len(printed), 3)
    check("pierwsza linia dot. 'blad A'", "blad A" in printed[0], True)
    check("druga linia dot. 'blad B'", "blad B" in printed[1], True)
    check("trzecia linia znow dot. 'blad A' (po resecie przez sukces)", "blad A" in printed[2], True)
    check("1 udany odczyt w srodku", recovered, 1)


def test_no_token_or_config_leak_in_error_lines():
    reader = _SequenceReader([OSError("low-level memory failure, code 5")])
    printed, _ = simulate_resilient_loop(reader, iterations=1)
    forbidden = ["token", "server_url", "tls_sha256_pin", "Bearer"]
    all_ok = True
    for f in forbidden:
        if f.lower() in printed[0].lower():
            all_ok = False
    check("brak odwolan do pol config.json w linii bledu", all_ok, True)


def test_parse_telemetry_value_error_also_handled():
    raw, err = safe_read_memory(_SequenceReader([b"\x00" * 5]))
    check_true("odczyt 'surowy' sie powiodl (reader.read() nie rzucil)", err is None and raw is not None)
    parsed, parse_err = safe_parse_telemetry(raw)
    check("parsed=None przy za krotkim buforze", parsed, None)
    check_true("parse_err opisuje ValueError", parse_err is not None and parse_err.startswith("ValueError:"))


if __name__ == "__main__":
    test_configure_sets_argtypes_and_restype_for_every_function()
    test_configure_is_idempotent_per_object()
    test_64bit_address_fits_c_void_p_without_overflow()
    test_default_ctypes_int_conversion_can_overflow_argumenterror()
    test_invalid_handle_value_matches_c_void_p_restype()
    test_single_read_error_then_recovery_prints_one_line()
    test_ctypes_argument_error_is_caught_too()
    test_repeated_identical_error_does_not_spam()
    test_error_message_changes_prints_new_line()
    test_no_token_or_config_leak_in_error_lines()
    test_parse_telemetry_value_error_also_handled()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy poprawki kernel32/petli (core.ets2_core) przeszły")
