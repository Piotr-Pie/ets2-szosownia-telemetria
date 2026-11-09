#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test parsera (port z client/tests/test_parser.py v0.1.3, import
dostosowany do core.ets2_core - logika BEZ ZMIAN)."""
import sys
import os
import ctypes as C

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import ScsTelemetryMap, parse_telemetry, MMF_SIZE  # noqa: E402

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = (abs(got - want) < 1e-3) if isinstance(want, float) else (got == want)
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def build_fake_memory(**kwargs) -> bytes:
    m = ScsTelemetryMap()
    C.memset(C.byref(m), 0, C.sizeof(m))
    m.sdkActive = kwargs.get("sdkActive", True)
    m.paused = kwargs.get("paused", False)
    m.truck_i.gear = kwargs.get("gear", 7)
    m.truck_f.speed = kwargs.get("speed", 24.2777)  # ~87.4 km/h
    m.truck_f.engineRpm = kwargs.get("engineRpm", 1450.0)
    m.truck_f.fuel = kwargs.get("fuel", 310.5)
    m.config_f.fuelCapacity = kwargs.get("fuelCapacity", 400.0)
    m.truck_f.truckOdometer = kwargs.get("truckOdometer", 12345.6)
    m.special_b.jobDelivered = kwargs.get("jobDelivered", False)
    m.gameplay_f.jobDeliveredDistanceKm = kwargs.get("distanceKm", 412.3)
    m.gameplay_i.jobDeliveredEarnedXp = kwargs.get("earnedXp", 1500)
    m.gameplay_ui.jobDeliveredDeliveryTime = kwargs.get("deliveryTime", 999)
    m.jobDeliveredRevenue_raw = kwargs.get("revenue", 18450)
    raw = bytes(m) + b"\x00" * (MMF_SIZE - C.sizeof(m))
    return raw


def test_basic_fields():
    raw = build_fake_memory()
    p = parse_telemetry(raw)
    check("sdk_active", p["sdk_active"], True)
    check("paused", p["paused"], False)
    check("gear", p["gear"], 7)
    check("speed_mps", p["speed_mps"], 24.2777)
    check("speed_kmh (x3.6)", round(p["speed_mps"] * 3.6, 1), 87.4)
    check("engine_rpm", p["engine_rpm"], 1450.0)
    check("fuel_l", p["fuel_l"], 310.5)
    check("fuel_capacity_l", p["fuel_capacity_l"], 400.0)
    check("odometer_km", p["odometer_km"], 12345.6)
    check("job_delivered_flag", p["job_delivered_flag"], False)
    check("job_delivered_distance_km", p["job_delivered_distance_km"], 412.3)
    check("job_delivered_earned_xp", p["job_delivered_earned_xp"], 1500)
    check("job_delivered_revenue", p["job_delivered_revenue"], 18450)


def test_revenue_raw_byte_offset():
    import struct

    needed = C.sizeof(ScsTelemetryMap)
    raw = bytearray(needed)
    revenue_value = 987654321
    struct.pack_into("<q", raw, 4208, revenue_value)
    p = parse_telemetry(bytes(raw))
    check("revenue na offsecie 4208 (bajty wstawione reczne)",
          p["job_delivered_revenue"], revenue_value)

    raw2 = bytearray(needed)
    struct.pack_into("<q", raw2, 4200, 111111)
    struct.pack_into("<q", raw2, 4208, 222222)
    struct.pack_into("<q", raw2, 4216, 333333)
    p2 = parse_telemetry(bytes(raw2))
    check("revenue nie miesza sie z sasiednimi polami (sasiedzi ustawione)",
          p2["job_delivered_revenue"], 222222)


def test_revenue_negative_raw_value_parses_as_is():
    raw = build_fake_memory(revenue=-500)
    p = parse_telemetry(raw)
    check("job_delivered_revenue (surowe, ujemne)", p["job_delivered_revenue"], -500)


def test_negative_gear_reverse():
    raw = build_fake_memory(gear=-1, speed=-2.0)
    p = parse_telemetry(raw)
    check("gear (wsteczny)", p["gear"], -1)
    check("speed_mps (wsteczny, ujemny)", p["speed_mps"], -2.0)


def test_paused_and_job_delivered_toggle():
    raw1 = build_fake_memory(jobDelivered=False)
    raw2 = build_fake_memory(jobDelivered=True)
    p1 = parse_telemetry(raw1)
    p2 = parse_telemetry(raw2)
    check("flag before", p1["job_delivered_flag"], False)
    check("flag after toggle", p2["job_delivered_flag"], True)


def test_too_short_buffer_raises():
    try:
        parse_telemetry(b"\x00" * 10)
        print("[FAIL] oczekiwano ValueError dla zbyt krotkiego bufora")
        global FAIL
        FAIL += 1
    except ValueError:
        print("[OK ] ValueError dla zbyt krotkiego bufora - zgodnie z oczekiwaniem")


if __name__ == "__main__":
    test_basic_fields()
    test_revenue_raw_byte_offset()
    test_revenue_negative_raw_value_parses_as_is()
    test_negative_gear_reverse()
    test_paused_and_job_delivered_toggle()
    test_too_short_buffer_raises()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy parsera (core.ets2_core) przeszły")
