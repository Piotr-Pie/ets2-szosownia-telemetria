#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy TelemetryWorker (core/telemetry_worker.py, kontrakt v5, v0.2.6):
pelny gating wysylki (wstrzymanie reczne, tryb automatyczny wg procesu
gry, pole baseline). Atrapy gniazda (FakeSender liczy bajty/pakiety -
ZERO prawdziwej sieci) i procesu (FakeProcessChecker - ZERO prawdziwego
Toolhelp32/Windows) - bez gry, bez Windows, zgodnie ze zleceniem.

tick() jest wolane WPROST (bez watku/sleep) - "symulowana jazda 60s"
oznacza N wywolan tick() z interwalem SEND_INTERVAL_CONNECTED (0.5s),
bez prawdziwego oczekiwania."""
import ctypes as C
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import ScsTelemetryMap, MMF_SIZE  # noqa: E402
from core.telemetry_worker import (  # noqa: E402
    TelemetryWorker, STATUS_ACTIVE, STATUS_MANUAL_PAUSED, STATUS_AUTO_PAUSED,
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


def build_fake_memory(onJob=True, speed_mps=25.0, fuel=300.0, jobDelivered=False) -> bytes:
    m = ScsTelemetryMap()
    C.memset(C.byref(m), 0, C.sizeof(m))
    m.sdkActive = True
    m.paused = False
    m.special_b.onJob = onJob
    m.special_b.jobDelivered = jobDelivered
    m.truck_f.speed = speed_mps
    m.truck_f.fuel = fuel
    m.truck_f.truckOdometer = 1000.0
    raw = bytes(m) + b"\x00" * (MMF_SIZE - C.sizeof(m))
    return raw


class FakeReader:
    """Atrapa SharedMemoryReader - .read() zwraca bajty gdy connected=True,
    inaczej None (gra/plugin niedostepny). Liczy wywolania (test wymaga
    'brak odczytu pamieci')."""

    def __init__(self):
        self.connected = True
        self.read_calls = 0
        self.onJob = True
        self.speed_mps = 25.0
        self.fuel = 300.0
        self.jobDelivered = False

    def read(self):
        self.read_calls += 1
        if not self.connected:
            return None
        return build_fake_memory(self.onJob, self.speed_mps, self.fuel, self.jobDelivered)


class FakeSender:
    """Atrapa TelemetrySender - ZERO prawdziwej sieci. Liczy pakiety i
    sumuje bajty (jak faktyczny json.dumps().encode() w send())."""

    def __init__(self):
        self.sent_packets = []
        self.total_bytes = 0

    def send(self, packet):
        body = json.dumps(packet).encode("utf-8")
        self.sent_packets.append(packet)
        self.total_bytes += len(body)
        return 202

    def backoff_sleep(self):
        pass


class FakeProcessChecker:
    """Atrapa is_game_process_running - liczy wywolania (test 'tylko
    sprawdzanie procesu')."""

    def __init__(self, running=True):
        self.running = running
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.running


def make_worker(reader=None, sender=None, process_checker=None, game_gate_enabled=True):
    reader = reader or FakeReader()
    sender = sender or FakeSender()
    process_checker = process_checker if process_checker is not None else FakeProcessChecker(True)
    statuses = []
    tooltips = []
    worker = TelemetryWorker(
        token="test-token",
        tls_sha256_pin=None,
        on_status=statuses.append,
        on_tooltip=tooltips.append,
        reader=reader,
        sender=sender,
        process_checker=process_checker,
        game_gate_enabled_fn=lambda: game_gate_enabled,
    )
    return worker, reader, sender, process_checker, statuses, tooltips


# ---------------------------------------------------------------------------
# 1) Wstrzymanie reczne: 0 bajtow przez >=60s symulowanej jazdy, w tym
#    brak heartbeat i brak pakietu connected=false.
# ---------------------------------------------------------------------------

def test_manual_pause_zero_bytes_60s_simulated():
    worker, reader, sender, proc, _, _ = make_worker()
    worker.pause()  # zaczyna wstrzymany domyslnie, ale wolamy jawnie - idempotentne
    check_true("po pause() worker.manual_paused", worker.manual_paused)

    now = 0.0
    for _ in range(130):  # 130 * 0.5s = 65s symulowanej jazdy
        interval = worker.tick(now=now)
        now += interval

    check("0 bajtow wyslanych w czasie wstrzymania recznego", sender.total_bytes, 0)
    check("0 pakietow wyslanych (brak heartbeat/connected=false)", len(sender.sent_packets), 0)
    check("brak odczytu pamieci SCS w czasie wstrzymania", reader.read_calls, 0)


# ---------------------------------------------------------------------------
# 2) Wznowienie reczne: pierwszy pakiet ma baseline=true, nastepne nie.
# ---------------------------------------------------------------------------

def test_manual_resume_first_packet_baseline_true_then_false():
    worker, reader, sender, proc, _, _ = make_worker()
    check_true("na starcie worker.manual_paused (wariant B)", worker.manual_paused)

    worker.resume()
    check_true("po resume() manual_paused == False", not worker.manual_paused)

    now = 0.0
    for _ in range(5):
        now += worker.tick(now=now)

    check_true("co najmniej 1 pakiet wyslany po wznowieniu", len(sender.sent_packets) >= 1)
    check("pierwszy pakiet po wznowieniu ma baseline=True",
          sender.sent_packets[0].get("baseline"), True)
    ok_rest = all("baseline" not in p for p in sender.sent_packets[1:])
    print(f"[{'OK ' if ok_rest else 'FAIL'}] kolejne pakiety NIE maja baseline: "
          f"{[p.get('baseline') for p in sender.sent_packets[1:]]}")
    global FAIL
    FAIL += 0 if ok_rest else 1


# ---------------------------------------------------------------------------
# 3) Gra wylaczona (atrapa procesu) -> 0 bajtow i brak odczytu pamieci.
# ---------------------------------------------------------------------------

def test_game_off_zero_bytes_and_no_memory_read():
    proc = FakeProcessChecker(running=False)
    worker, reader, sender, _, _, _ = make_worker(process_checker=proc)
    worker.resume()

    now = 0.0
    for _ in range(20):
        now += worker.tick(now=now)

    check_true("worker.auto_paused == True (gra nie dziala)", worker.auto_paused)
    check("0 bajtow wyslanych - gra wylaczona", sender.total_bytes, 0)
    check("brak odczytu pamieci SCS - gra wylaczona", reader.read_calls, 0)
    check_true("proces byl sprawdzany (poll)", proc.calls > 0)


# ---------------------------------------------------------------------------
# 4) Gra wlaczona po wylaczeniu -> wznowienie z baseline, bez klikniecia.
# ---------------------------------------------------------------------------

def test_game_turns_on_after_off_autoresumes_with_baseline_without_click():
    proc = FakeProcessChecker(running=False)
    worker, reader, sender, _, _, _ = make_worker(process_checker=proc)
    worker.resume()

    now = 0.0
    for _ in range(5):
        now += worker.tick(now=now)
    check("0 pakietow, gra wylaczona", len(sender.sent_packets), 0)

    # Gra "wlacza sie" sama - BEZ zadnego klikniecia w UI.
    proc.running = True
    for _ in range(5):
        now += worker.tick(now=now)

    check_true("worker.auto_paused == False po powrocie gry", not worker.auto_paused)
    check_true("co najmniej 1 pakiet wyslany po powrocie gry", len(sender.sent_packets) >= 1)
    check("pierwszy pakiet po automatycznym wznowieniu ma baseline=True",
          sender.sent_packets[0].get("baseline"), True)


# ---------------------------------------------------------------------------
# 5) Reczne wstrzymanie + gra wlaczona -> 0 bajtow (automat nie wznawia).
# ---------------------------------------------------------------------------

def test_manual_pause_wins_over_running_game():
    proc = FakeProcessChecker(running=True)
    worker, reader, sender, _, _, _ = make_worker(process_checker=proc)
    worker.pause()  # reczne wstrzymanie, mimo ze gra "dziala"

    now = 0.0
    for _ in range(20):
        now += worker.tick(now=now)

    check("0 bajtow - reczne wstrzymanie wygrywa z automatem (gra wlaczona)",
          sender.total_bytes, 0)
    check("0 wywolan sprawdzania procesu w czasie recznego wstrzymania",
          proc.calls, 0)


# ---------------------------------------------------------------------------
# 6) Przelacznik "Wysylaj tylko gdy gra dziala" WYLACZONY + gra wylaczona
#    -> wysylka DZIALA (kontrola dzialania przelacznika w obie strony).
# ---------------------------------------------------------------------------

def test_game_gate_disabled_sends_even_when_game_off():
    proc = FakeProcessChecker(running=False)
    worker, reader, sender, _, _, _ = make_worker(process_checker=proc, game_gate_enabled=False)
    worker.resume()

    now = 0.0
    for _ in range(5):
        now += worker.tick(now=now)

    check_true("worker.auto_paused == False (gate wylaczony)", not worker.auto_paused)
    check_true("pakiety wysylane mimo wylaczonej gry (gate wylaczony)",
                len(sender.sent_packets) > 0)


# ---------------------------------------------------------------------------
# 7) Start z autostartu -> 0 bajtow do "Wznow" (wariant B, BEZ ZMIAN).
# ---------------------------------------------------------------------------

def test_fresh_worker_starts_paused_zero_bytes_until_resume():
    worker, reader, sender, proc, _, _ = make_worker()
    check_true("worker ZAWSZE zaczyna wstrzymany (wariant B)", worker.manual_paused)

    now = 0.0
    for _ in range(10):
        now += worker.tick(now=now)
    check("0 bajtow przed pierwszym resume()", sender.total_bytes, 0)
    check("0 odczytow pamieci przed pierwszym resume()", reader.read_calls, 0)


# ---------------------------------------------------------------------------
# 8) Zerowanie statystyk zlecenia przy wstrzymaniu.
# ---------------------------------------------------------------------------

def test_job_stats_reset_on_manual_pause():
    reader = FakeReader()
    reader.onJob = True
    reader.speed_mps = 25.0  # 90 km/h
    reader.fuel = 300.0
    worker, _, sender, _, _, _ = make_worker(reader=reader)
    worker.resume()

    now = 0.0
    for _ in range(10):  # kilka probek "w trasie", zlecenie aktywne
        now += worker.tick(now=now)

    acc = worker._tracker._job_stats
    check_true("akumulator statystyk zlecenia aktywny przed wstrzymaniem", acc.active)

    worker.pause()

    check_true("akumulator wyzerowany po recznym wstrzymaniu", not acc.active)
    check("moving_time_s wyzerowany", acc.moving_time_s, 0.0)
    check("max_speed_kmh wyzerowany", acc.max_speed_kmh, 0.0)
    check("fuel_used_l wyzerowany", acc.fuel_used_l, 0.0)


def test_job_stats_reset_on_auto_pause():
    reader = FakeReader()
    reader.onJob = True
    proc = FakeProcessChecker(running=True)
    worker, _, sender, _, _, _ = make_worker(reader=reader, process_checker=proc)
    worker.resume()

    now = 0.0
    for _ in range(10):
        now += worker.tick(now=now)

    acc = worker._tracker._job_stats
    check_true("akumulator aktywny przed wylaczeniem gry", acc.active)

    proc.running = False
    now += worker.tick(now=now)

    check_true("akumulator wyzerowany po automatycznym wstrzymaniu", not acc.active)


# ---------------------------------------------------------------------------
# 9) Tooltip: dokladnie 3 teksty z kontraktu v5 SS1.
# ---------------------------------------------------------------------------

def test_tooltip_exact_three_canonical_texts():
    proc = FakeProcessChecker(running=True)
    worker, reader, sender, _, _, tooltips = make_worker(process_checker=proc)

    check("status_text() na starcie == wstrzymana przez gracza",
          worker.status_text(), STATUS_MANUAL_PAUSED)

    worker.resume()
    now = 0.0
    now += worker.tick(now=now)
    check("status_text() po resume() == wysyłka aktywna",
          worker.status_text(), STATUS_ACTIVE)

    proc.running = False
    now += worker.tick(now=now)
    check("status_text() gdy gra wylaczona == czeka na uruchomienie gry",
          worker.status_text(), STATUS_AUTO_PAUSED)

    all_canonical = all(
        t in (STATUS_ACTIVE, STATUS_MANUAL_PAUSED, STATUS_AUTO_PAUSED) for t in tooltips
    )
    print(f"[{'OK ' if all_canonical else 'FAIL'}] WSZYSTKIE tooltipy nalezaly do 3 kanonicznych "
          f"tekstow: {tooltips}")
    global FAIL
    FAIL += 0 if all_canonical else 1


if __name__ == "__main__":
    test_manual_pause_zero_bytes_60s_simulated()
    test_manual_resume_first_packet_baseline_true_then_false()
    test_game_off_zero_bytes_and_no_memory_read()
    test_game_turns_on_after_off_autoresumes_with_baseline_without_click()
    test_manual_pause_wins_over_running_game()
    test_game_gate_disabled_sends_even_when_game_off()
    test_fresh_worker_starts_paused_zero_bytes_until_resume()
    test_job_stats_reset_on_manual_pause()
    test_job_stats_reset_on_auto_pause()
    test_tooltip_exact_three_canonical_texts()
    print()
    if FAIL:
        print(f"WYNIK: {FAIL} testów nieudanych")
        sys.exit(1)
    print("WYNIK: wszystkie testy TelemetryWorker (gating, kontrakt v5) przeszły")
