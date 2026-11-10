#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy statystyk dostawy (job_stats, kontrakt v4, v0.2.5) - akumulator
syntetyczny (core.job_stats.JobStatsAccumulator) oraz integracja z
EventTracker/build_packet (core.ets2_core) - docs/telemetry-contract-v4.md
S1/S2. Bez gry - wylacznie probki syntetyczne."""
import sys
import os
import ctypes as C

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.job_stats import JobStatsAccumulator  # noqa: E402
from core.ets2_core import (  # noqa: E402
    ScsTelemetryMap, parse_telemetry, build_packet, EventTracker, MMF_SIZE,
    _sanitize_fuel_avg_consumption_pct,
)

FAIL = 0


def check(label, got, want, tol=1e-3):
    global FAIL
    ok = (abs(got - want) < tol) if isinstance(want, float) else (got == want)
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def build_fake_memory_job(onJob=True, fuelAvgConsumption=0.0, jobDelivered=False):
    """Pamiec syntetyczna z ustawionym truck_f.fuelAvgConsumption i
    special_b.onJob - do testow pakietu/EventTracker."""
    m = ScsTelemetryMap()
    C.memset(C.byref(m), 0, C.sizeof(m))
    m.sdkActive = True
    m.paused = False
    m.special_b.onJob = onJob
    m.special_b.jobDelivered = jobDelivered
    m.truck_f.fuelAvgConsumption = fuelAvgConsumption
    raw = bytes(m) + b"\x00" * (MMF_SIZE - C.sizeof(m))
    return raw


# ---------------------------------------------------------------------------
# 1) Stala predkosc 90 km/h przez 1h, probki co 1s -> moving_time_s=3600,
#    avg_speed_kmh=90 (+-0.5)
# ---------------------------------------------------------------------------

def test_constant_speed_90kmh_1h():
    acc = JobStatsAccumulator()
    acc.start_if_needed(True)
    fuel = 500.0
    for i in range(3601):  # t=0..3600s wlacznie -> 3600 odstepow 1s
        acc.sample(90.0, fuel, now=float(i))
    check("moving_time_s po 1h przy 90 km/h", acc.moving_time_s, 3600.0, tol=0.5)
    result = acc.finish_delivery(distance_km=90.0)  # 90 km/h * 1h = 90 km
    check("avg_speed_kmh (90km / 1h)", result["avg_speed_kmh"], 90.0, tol=0.5)
    check("fuel_used_l (brak spadku paliwa)", result["fuel_used_l"], 0.0)


# ---------------------------------------------------------------------------
# 2) Spadek paliwa i tankowanie w srodku zlecenia - tankowanie NIE
#    zwieksza fuel_used_l
# ---------------------------------------------------------------------------

def test_fuel_drop_and_refuel_mid_job():
    acc = JobStatsAccumulator()
    acc.start_if_needed(True)
    acc.sample(50.0, 100.0, now=0.0)
    acc.sample(50.0, 90.0, now=1.0)   # spadek 10 -> liczone
    acc.sample(50.0, 95.0, now=2.0)   # tankowanie (+5) -> IGNOROWANE
    acc.sample(50.0, 80.0, now=3.0)   # spadek 15 -> liczone
    check("fuel_used_l = suma spadkow, tankowanie zignorowane",
          acc.fuel_used_l, 25.0)


# ---------------------------------------------------------------------------
# 3) Predkosc 250 km/h w jednej probce -> max_speed_kmh = 200 (przyciete)
# ---------------------------------------------------------------------------

def test_speed_250_capped_to_200():
    acc = JobStatsAccumulator()
    acc.start_if_needed(True)
    acc.sample(250.0, 500.0, now=0.0)
    check("max_speed_kmh przyciete do 200 (probka 250 km/h)",
          acc.max_speed_kmh, 200.0)
    result = acc.finish_delivery(distance_km=10.0)
    check("max_speed_kmh w zdarzeniu przyciete do 200",
          result["max_speed_kmh"], 200.0)


# ---------------------------------------------------------------------------
# 4) Przerwa 30s miedzy probkami -> dt przyciete do 2s
# ---------------------------------------------------------------------------

def test_gap_30s_dt_capped_to_2s():
    acc = JobStatsAccumulator()
    acc.start_if_needed(True)
    acc.sample(50.0, 500.0, now=0.0)
    acc.sample(50.0, 500.0, now=30.0)  # przerwa 30s (np. pauza/menu gry)
    check("moving_time_s po przerwie 30s = dt przyciete do 2s",
          acc.moving_time_s, 2.0)


# ---------------------------------------------------------------------------
# 5) distance_km = 0.3 -> avg_consumption_l_per_100km = null
# ---------------------------------------------------------------------------

def test_short_distance_consumption_null():
    acc = JobStatsAccumulator()
    acc.start_if_needed(True)
    acc.sample(50.0, 100.0, now=0.0)
    acc.sample(50.0, 95.0, now=1.0)  # spadek 5l, ale distance < 0.5km
    result = acc.finish_delivery(distance_km=0.3)
    ok = result["avg_consumption_l_per_100km"] is None
    print(f"[{'OK ' if ok else 'FAIL'}] distance_km=0.3 -> avg_consumption_l_per_100km None: "
          f"{result['avg_consumption_l_per_100km']!r}")
    global FAIL
    FAIL += 0 if ok else 1


# ---------------------------------------------------------------------------
# 6) Rozlaczenie w polowie zlecenia -> brak wysylki zdarzenia, akumulator
#    wyzerowany (EventTracker.on_disconnected, wolane z petli w app.py gdy
#    connected=False)
# ---------------------------------------------------------------------------

def test_disconnect_mid_job_resets_without_event():
    tracker = EventTracker()
    raw_on_job = build_fake_memory_job(onJob=True, jobDelivered=False)
    parsed = parse_telemetry(raw_on_job)

    # kilka probek "w trasie" zanim nastapi rozlaczenie
    for _ in range(5):
        ev = tracker.check(parsed)
        assert ev is None

    acc = tracker._job_stats
    was_active_before = acc.active
    print(f"[{'OK ' if was_active_before else 'FAIL'}] akumulator aktywny przed rozlaczeniem: {was_active_before}")
    global FAIL
    FAIL += 0 if was_active_before else 1

    # rozlaczenie - wolane z petli glownej, GDY connected=False w tym ticku
    tracker.on_disconnected()

    ok_reset = (not acc.active and acc.moving_time_s == 0.0
                and acc.max_speed_kmh == 0.0 and acc.fuel_used_l == 0.0)
    print(f"[{'OK ' if ok_reset else 'FAIL'}] akumulator wyzerowany po rozlaczeniu: "
          f"active={acc.active}, moving_time_s={acc.moving_time_s}, "
          f"max_speed_kmh={acc.max_speed_kmh}, fuel_used_l={acc.fuel_used_l}")
    FAIL += 0 if ok_reset else 1


# ---------------------------------------------------------------------------
# 7) Pakiet: "v": 4; fuel_avg_consumption_l_per_100km null przy wartosci
#    odpowiadajacej 0 i 150 l/100km
# ---------------------------------------------------------------------------

def test_packet_v4_and_fuel_avg_consumption_null_cases():
    raw = build_fake_memory_job(onJob=False, fuelAvgConsumption=0.02)  # 2 l/100km, poprawna
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    check("packet v == 5 (kontrakt v5, v0.2.6)", packet["v"], 5)
    check("fuel_avg_consumption_l_per_100km poprawna wartosc (2 l/100km)",
          packet["truck"]["fuel_avg_consumption_l_per_100km"], 2.0)

    # 0 l/100km (fuelAvgConsumption=0.0 l/km) -> pct<=0 -> null
    ok_zero = _sanitize_fuel_avg_consumption_pct(0.0) is None
    print(f"[{'OK ' if ok_zero else 'FAIL'}] fuelAvgConsumption=0.0 (l/km) -> pct null: "
          f"{_sanitize_fuel_avg_consumption_pct(0.0)!r}")
    global FAIL
    FAIL += 0 if ok_zero else 1

    # 150 l/100km (fuelAvgConsumption=1.5 l/km) -> pct>100 -> null
    ok_150 = _sanitize_fuel_avg_consumption_pct(1.5) is None
    print(f"[{'OK ' if ok_150 else 'FAIL'}] fuelAvgConsumption=1.5 l/km (150 l/100km) -> pct null: "
          f"{_sanitize_fuel_avg_consumption_pct(1.5)!r}")
    FAIL += 0 if ok_150 else 1


if __name__ == "__main__":
    test_constant_speed_90kmh_1h()
    test_fuel_drop_and_refuel_mid_job()
    test_speed_250_capped_to_200()
    test_gap_30s_dt_capped_to_2s()
    test_short_distance_consumption_null()
    test_disconnect_mid_job_resets_without_event()
    test_packet_v4_and_fuel_avg_consumption_null_cases()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy statystyk dostawy (job_stats, kontrakt v4) przeszły")
