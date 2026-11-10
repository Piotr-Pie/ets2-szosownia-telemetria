#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test parsera (port z client/tests/test_parser.py v0.1.3, import
dostosowany do core.ets2_core - logika BEZ ZMIAN)."""
import sys
import os
import ctypes as C

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import (  # noqa: E402
    ScsTelemetryMap, parse_telemetry, build_position, build_packet, MMF_SIZE,
)

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
    m.truck_dp.coordinateX = kwargs.get("coordinateX", 123456.78)
    m.truck_dp.coordinateY = kwargs.get("coordinateY", 12.3)
    m.truck_dp.coordinateZ = kwargs.get("coordinateZ", -98765.43)
    m.truck_dp.rotationX = kwargs.get("rotationX", 0.75)  # heading fraction
    m.truck_dp.rotationY = kwargs.get("rotationY", 0.01)  # pitch
    m.truck_dp.rotationZ = kwargs.get("rotationZ", -0.02)  # roll
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


# ---------------------------------------------------------------------------
# Testy pozycji ciezarowki (truck.position, kontrakt v2, v0.2.1) - port
# 1:1 z client/tests/test_parser.py (v0.1.4), logika BEZ ZMIAN.
# ---------------------------------------------------------------------------

def test_position_offsets_coordinateX_Y_Z():
    raw = build_fake_memory(coordinateX=111111.1, coordinateY=222222.2,
                             coordinateZ=333333.3, rotationX=0.0)
    p = parse_telemetry(raw)
    check("pos_x (offset 2200)", p["pos_x"], 111111.1)
    check("pos_y (offset 2208)", p["pos_y"], 222222.2)
    check("pos_z (offset 2216)", p["pos_z"], 333333.3)


def test_position_offset_rotationX_heading_raw_bytes():
    import struct

    needed = C.sizeof(ScsTelemetryMap)
    raw = bytearray(needed)
    struct.pack_into("<d", raw, 2200, 500000.5)
    struct.pack_into("<d", raw, 2208, 100.25)
    struct.pack_into("<d", raw, 2216, -300000.75)
    struct.pack_into("<d", raw, 2224, 0.5)
    p = parse_telemetry(bytes(raw))
    check("pos_x na offsecie 2200 (bajty wstawione reczne)", p["pos_x"], 500000.5)
    check("pos_y na offsecie 2208 (bajty wstawione reczne)", p["pos_y"], 100.25)
    check("pos_z na offsecie 2216 (bajty wstawione reczne)", p["pos_z"], -300000.75)
    check("heading_fraction na offsecie 2224 (bajty wstawione reczne)",
          p["heading_fraction"], 0.5)

    raw2 = bytearray(needed)
    struct.pack_into("<d", raw2, 2200, 1.0)
    struct.pack_into("<q", raw2, 4208, 99)
    p2 = parse_telemetry(bytes(raw2))
    check("pos_x nie miesza sie z revenue (zony nie nakladaja sie)",
          p2["pos_x"], 1.0)
    check("revenue nie miesza sie z pos_x (zony nie nakladaja sie)",
          p2["job_delivered_revenue"], 99)


def test_build_position_valid_values():
    raw = build_fake_memory(coordinateX=123456.78, coordinateY=12.3,
                             coordinateZ=-98765.43, rotationX=0.7542)
    p = parse_telemetry(raw)
    pos = build_position(p)
    check("build_position nie jest None dla wartosci skonczonych",
          pos is not None, True)
    check("build_position x", pos["x"], 123456.78)
    check("build_position y", pos["y"], 12.3)
    check("build_position z", pos["z"], -98765.43)
    check("build_position heading_deg (0.7542*360=271.512 -> 271.5)",
          pos["heading_deg"], 271.5)


def test_build_position_heading_range_0_360():
    cases = [
        (0.0, 0.0), (0.25, 90.0), (0.5, 180.0),
        (0.9997222, 359.9), (-0.1, 324.0), (1.0, 0.0),
    ]
    for heading_fraction, want in cases:
        raw = build_fake_memory(rotationX=heading_fraction)
        p = parse_telemetry(raw)
        pos = build_position(p)
        ok = pos is not None and 0.0 <= pos["heading_deg"] < 360.0
        print(f"[{'OK ' if ok else 'FAIL'}] heading_deg w [0,360) dla "
              f"rotationX={heading_fraction}: got={pos['heading_deg'] if pos else None}")
        global FAIL
        FAIL += 0 if ok else 1
        check(f"heading_deg dla rotationX={heading_fraction}",
              pos["heading_deg"], want)


def test_build_position_nan_or_inf_returns_none():
    nan = float("nan")
    inf = float("inf")
    cases = {
        "pos_x NaN": dict(pos_x=nan, pos_y=1.0, pos_z=1.0, heading_fraction=0.1),
        "pos_y +inf": dict(pos_x=1.0, pos_y=inf, pos_z=1.0, heading_fraction=0.1),
        "pos_z -inf": dict(pos_x=1.0, pos_y=1.0, pos_z=-inf, heading_fraction=0.1),
        "heading NaN": dict(pos_x=1.0, pos_y=1.0, pos_z=1.0, heading_fraction=nan),
    }
    for label, parsed in cases.items():
        pos = build_position(parsed)
        ok = pos is None
        print(f"[{'OK ' if ok else 'FAIL'}] build_position None dla {label}: got={pos}")
        global FAIL
        FAIL += 0 if ok else 1


def test_build_packet_v2_includes_position_when_connected():
    raw = build_fake_memory()
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    check("packet v == 4 (kontrakt v4, v0.2.5)", packet["v"], 4)
    has_pos = "position" in packet.get("truck", {})
    print(f"[{'OK ' if has_pos else 'FAIL'}] packet zawiera truck.position gdy connected: {has_pos}")
    global FAIL
    FAIL += 0 if has_pos else 1


def test_build_packet_omits_position_when_nan():
    raw = build_fake_memory(rotationX=float("nan"))
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    no_pos = "position" not in packet.get("truck", {})
    has_other_fields = "speed_kmh" in packet.get("truck", {})
    print(f"[{'OK ' if no_pos else 'FAIL'}] packet NIE zawiera truck.position gdy heading=NaN: {no_pos}")
    print(f"[{'OK ' if has_other_fields else 'FAIL'}] reszta truck.* nadal wyslana: {has_other_fields}")
    global FAIL
    FAIL += 0 if no_pos else 1
    FAIL += 0 if has_other_fields else 1


def test_build_packet_v2_without_position_when_not_connected():
    packet = build_packet(connected=False, running=True, parsed=None, events=[])
    check("packet v == 4 nawet bez polaczenia", packet["v"], 4)
    no_truck = "truck" not in packet
    print(f"[{'OK ' if no_truck else 'FAIL'}] brak pola truck gdy connected=False: {no_truck}")
    global FAIL
    FAIL += 0 if no_truck else 1
    no_job = "job" not in packet
    print(f"[{'OK ' if no_job else 'FAIL'}] brak pola job gdy connected=False: {no_job}")
    FAIL += 0 if no_job else 1


if __name__ == "__main__":
    test_basic_fields()
    test_revenue_raw_byte_offset()
    test_revenue_negative_raw_value_parses_as_is()
    test_negative_gear_reverse()
    test_paused_and_job_delivered_toggle()
    test_too_short_buffer_raises()
    test_position_offsets_coordinateX_Y_Z()
    test_position_offset_rotationX_heading_raw_bytes()
    test_build_position_valid_values()
    test_build_position_heading_range_0_360()
    test_build_position_nan_or_inf_returns_none()
    test_build_packet_v2_includes_position_when_connected()
    test_build_packet_omits_position_when_nan()
    test_build_packet_v2_without_position_when_not_connected()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy parsera (core.ets2_core) przeszły")
