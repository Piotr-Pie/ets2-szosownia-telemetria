#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy zlecenia (job, kontrakt v3, v0.2.4): offsety pol w pamieci SCS
(bajty syntetyczne, bez nakladania zon), parser (parse_telemetry), budowa
obiektu job (build_job) i budowa pakietu (build_packet) wg reguł kontraktu
v3 - docs/telemetry-contract-v3.md."""
import sys
import os
import struct
import ctypes as C

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import (  # noqa: E402
    ScsTelemetryMap, parse_telemetry, build_job, build_packet, MMF_SIZE,
)

FAIL = 0


def check(label, got, want):
    global FAIL
    ok = (abs(got - want) < 1e-3) if isinstance(want, float) else (got == want)
    status = "OK " if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{status}] {label}: got={got!r} want={want!r}")


def build_fake_job_memory(**kwargs) -> bytes:
    """Jak build_fake_memory() w test_parser.py, ale z polami zlecenia."""
    m = ScsTelemetryMap()
    C.memset(C.byref(m), 0, C.sizeof(m))
    m.sdkActive = True
    m.paused = False
    m.special_b.onJob = kwargs.get("onJob", True)
    m.cargo = kwargs.get("cargo", b"Ryby")
    m.config_f.cargoMass = kwargs.get("cargoMass", 12000.0)
    m.job_f.cargoDamage = kwargs.get("cargoDamage", 0.0)
    m.citySrc = kwargs.get("citySrc", b"Berlin")
    m.cityDst = kwargs.get("cityDst", b"Hamburg")
    m.jobMarket = kwargs.get("jobMarket", b"quick_job")
    m.jobIncome = kwargs.get("jobIncome", 18450)
    m.config_ui.plannedDistanceKm = kwargs.get("plannedDistanceKm", 290)
    m.truck_f.routeDistance = kwargs.get("routeDistance", 143200.0)  # metry!
    m.truck_f.routeTime = kwargs.get("routeTime", 4440.0)  # sekundy (74 min)
    raw = bytes(m) + b"\x00" * (MMF_SIZE - C.sizeof(m))
    return raw


# ---------------------------------------------------------------------------
# 1) Offsety - bajty wstawione reczne przy struct.pack_into, zero nakladania
#    stref (kazde pole osobno, zweryfikowane wzgledem tabeli w raporcie).
# ---------------------------------------------------------------------------

def test_offsets_no_overlap():
    needed = C.sizeof(ScsTelemetryMap)

    raw = bytearray(needed)
    raw[2620:2620 + 5] = b"Ryby\x00"
    raw[2748:2748 + 8] = b"Hamburg\x00"
    raw[3004:3004 + 7] = b"Berlin\x00"
    raw[3404:3404 + 10] = b"quick_job\x00"
    struct.pack_into("<Q", raw, 4000, 18450)
    p = parse_telemetry(bytes(raw))
    check("cargo na offsecie 2620", p["cargo_raw"].split(b"\x00", 1)[0], b"Ryby")
    check("cityDst na offsecie 2748", p["destination_city_raw"].split(b"\x00", 1)[0], b"Hamburg")
    check("citySrc na offsecie 3004", p["source_city_raw"].split(b"\x00", 1)[0], b"Berlin")
    check("jobMarket na offsecie 3404", p["market_raw"].split(b"\x00", 1)[0], b"quick_job")
    check("jobIncome na offsecie 4000", p["job_income_raw"], 18450)

    # sasiedzi tez ustawieni - zony nie moga sie mieszac z revenue (4208)
    raw2 = bytearray(needed)
    raw2[2620:2620 + 5] = b"Drewno\x00"[:5]
    struct.pack_into("<Q", raw2, 4000, 999)
    struct.pack_into("<q", raw2, 4208, 555)
    p2 = parse_telemetry(bytes(raw2))
    check("cargo nie miesza sie z revenue", p2["cargo_raw"][:4], b"Drew")
    check("jobIncome nie miesza sie z revenue", p2["job_income_raw"], 999)


def test_config_ui_mass_damage_route_already_modeled():
    raw = build_fake_job_memory(
        cargoMass=12000.0, cargoDamage=0.05, plannedDistanceKm=290,
        routeDistance=143200.0, routeTime=4440.0,
    )
    p = parse_telemetry(raw)
    check("cargo_mass_kg_raw (config_f.cargoMass)", p["cargo_mass_kg_raw"], 12000.0)
    check("cargo_damage_fraction_raw (job_f.cargoDamage)", p["cargo_damage_fraction_raw"], 0.05)
    check("planned_distance_km_raw (config_ui.plannedDistanceKm)", p["planned_distance_km_raw"], 290)
    check("route_distance_m_raw (truck_f.routeDistance, METRY)", p["route_distance_m_raw"], 143200.0)
    check("route_time_s_raw (truck_f.routeTime, SEKUNDY)", p["route_time_s_raw"], 4440.0)


# ---------------------------------------------------------------------------
# 2) Parser + sanitizacja stringow (\0, znaki sterujace, obciecie)
# ---------------------------------------------------------------------------

def test_string_with_embedded_null_and_control_chars():
    raw = build_fake_job_memory(cargo=b"Ryby\x00SMIECIE_PO_ZERZE")
    p = parse_telemetry(raw)
    job = build_job(p)
    check("cargo odciety do pierwszego \\0", job.get("cargo"), "Ryby")

    raw2 = build_fake_job_memory(cargo=b"Ry\x01\x02by\x07")
    p2 = parse_telemetry(raw2)
    job2 = build_job(p2)
    check("cargo bez znakow sterujacych", job2.get("cargo"), "Ryby")

    raw3 = build_fake_job_memory(cargo=b"")
    p3 = parse_telemetry(raw3)
    job3 = build_job(p3)
    has_cargo = "cargo" in job3
    print(f"[{'OK ' if not has_cargo else 'FAIL'}] cargo pusty -> pole pominiete: {job3.get('cargo')!r}")
    global FAIL
    FAIL += 0 if not has_cargo else 1


def test_string_truncated_to_limit():
    long_market = (b"x" * 40)  # > 32, ale bufor w pamieci i tak max 32 bajty
    raw = build_fake_job_memory(jobMarket=long_market[:32])
    p = parse_telemetry(raw)
    job = build_job(p)
    ok = len(job.get("market", "")) <= 32
    print(f"[{'OK ' if ok else 'FAIL'}] market <= 32 znaki: len={len(job.get('market', ''))}")
    global FAIL
    FAIL += 0 if ok else 1


# ---------------------------------------------------------------------------
# 3) NaN/inf w liczbach -> pole pominiete (nie caly pakiet)
# ---------------------------------------------------------------------------

def test_nan_inf_fields_omitted_individually():
    nan = float("nan")
    inf = float("inf")

    raw = build_fake_job_memory(cargoMass=nan)
    p = parse_telemetry(raw)
    job = build_job(p)
    ok1 = "cargo_mass_kg" not in job and "cargo" in job
    print(f"[{'OK ' if ok1 else 'FAIL'}] cargoMass=NaN -> cargo_mass_kg pominiete, reszta job zostaje: {job}")
    global FAIL
    FAIL += 0 if ok1 else 1

    raw2 = build_fake_job_memory(routeDistance=inf)
    p2 = parse_telemetry(raw2)
    job2 = build_job(p2)
    ok2 = "remaining_distance_km" not in job2 and "market" in job2
    print(f"[{'OK ' if ok2 else 'FAIL'}] routeDistance=+inf -> remaining_distance_km pominiete: {job2}")
    FAIL += 0 if ok2 else 1

    raw3 = build_fake_job_memory(routeTime=nan)
    p3 = parse_telemetry(raw3)
    job3 = build_job(p3)
    ok3 = "remaining_time_min" not in job3
    print(f"[{'OK ' if ok3 else 'FAIL'}] routeTime=NaN -> remaining_time_min pominiete: {job3}")
    FAIL += 0 if ok3 else 1


def test_negative_values_omitted():
    raw = build_fake_job_memory(cargoMass=-5.0)
    p = parse_telemetry(raw)
    job = build_job(p)
    ok = "cargo_mass_kg" not in job
    print(f"[{'OK ' if ok else 'FAIL'}] cargoMass ujemna -> cargo_mass_kg pominiete: {job.get('cargo_mass_kg')}")
    global FAIL
    FAIL += 0 if ok else 1


def test_cargo_damage_pct_range_and_conversion():
    raw = build_fake_job_memory(cargoDamage=0.5)  # ulamek 0.5 -> 50%
    p = parse_telemetry(raw)
    job = build_job(p)
    check("cargo_damage_pct = cargoDamage*100", job.get("cargo_damage_pct"), 50.0)

    raw2 = build_fake_job_memory(cargoDamage=float("nan"))
    p2 = parse_telemetry(raw2)
    job2 = build_job(p2)
    ok = "cargo_damage_pct" not in job2
    print(f"[{'OK ' if ok else 'FAIL'}] cargoDamage=NaN -> cargo_damage_pct pominiete: {job2.get('cargo_damage_pct')}")
    global FAIL
    FAIL += 0 if ok else 1


def test_remaining_distance_km_unit_conversion_from_meters():
    # routeDistance w pamieci SCS jest w METRACH (SDK: "in meters") - klient
    # dzieli przez 1000. 143200 m -> 143.2 km.
    raw = build_fake_job_memory(routeDistance=143200.0)
    p = parse_telemetry(raw)
    job = build_job(p)
    check("remaining_distance_km = routeDistance(m)/1000", job.get("remaining_distance_km"), 143.2)


def test_remaining_time_min_unit_conversion_from_seconds():
    # routeTime w pamieci SCS jest w SEKUNDACH (SDK: "in second") - klient
    # dzieli przez 60. 4440 s -> 74.0 min.
    raw = build_fake_job_memory(routeTime=4440.0)
    p = parse_telemetry(raw)
    job = build_job(p)
    check("remaining_time_min = routeTime(s)/60", job.get("remaining_time_min"), 74.0)


# ---------------------------------------------------------------------------
# 4) build_packet(): reguly wysylania job wg kontraktu v3
# ---------------------------------------------------------------------------

def test_build_packet_onjob_true_includes_job_object():
    raw = build_fake_job_memory(onJob=True)
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    check("v == 5 (kontrakt v5, v0.2.6)", packet["v"], 5)
    ok = isinstance(packet.get("job"), dict) and packet["job"].get("cargo") == "Ryby"
    print(f"[{'OK ' if ok else 'FAIL'}] onJob=True -> job jest obiektem: {packet.get('job')}")
    global FAIL
    FAIL += 0 if ok else 1


def test_build_packet_onjob_false_sends_job_null():
    raw = build_fake_job_memory(onJob=False)
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    has_key = "job" in packet
    is_none = packet.get("job") is None
    print(f"[{'OK ' if (has_key and is_none) else 'FAIL'}] onJob=False, connected=True -> \"job\": null: {packet.get('job')!r}, has_key={has_key}")
    global FAIL
    FAIL += 0 if (has_key and is_none) else 1


def test_build_packet_not_connected_omits_job_key():
    packet = build_packet(connected=False, running=True, parsed=None, events=[])
    no_job = "job" not in packet
    print(f"[{'OK ' if no_job else 'FAIL'}] connected=False -> brak pola job w pakiecie: {no_job} (packet={packet})")
    global FAIL
    FAIL += 0 if no_job else 1


def test_build_packet_rejects_out_of_range_cargo_damage_by_omitting_field():
    # cargoDamage > 1.0 (nieprawidlowa wartosc z pamieci) -> *100 > 100 ->
    # pole cargo_damage_pct pominiete, ale PAKIET i reszta job nadal wyslane.
    raw = build_fake_job_memory(cargoDamage=1.5)
    p = parse_telemetry(raw)
    packet = build_packet(connected=True, running=True, parsed=p, events=[])
    job = packet.get("job")
    ok = job is not None and "cargo_damage_pct" not in job and "cargo" in job
    print(f"[{'OK ' if ok else 'FAIL'}] cargoDamage=1.5 (>100% po *100) -> pole pominiete, reszta job zostaje: {job}")
    global FAIL
    FAIL += 0 if ok else 1


if __name__ == "__main__":
    test_offsets_no_overlap()
    test_config_ui_mass_damage_route_already_modeled()
    test_string_with_embedded_null_and_control_chars()
    test_string_truncated_to_limit()
    test_nan_inf_fields_omitted_individually()
    test_negative_values_omitted()
    test_cargo_damage_pct_range_and_conversion()
    test_remaining_distance_km_unit_conversion_from_meters()
    test_remaining_time_min_unit_conversion_from_seconds()
    test_build_packet_onjob_true_includes_job_object()
    test_build_packet_onjob_false_sends_job_null()
    test_build_packet_not_connected_omits_job_key()
    test_build_packet_rejects_out_of_range_cargo_damage_by_omitting_field()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy zlecenia (job, kontrakt v3) przeszły")
