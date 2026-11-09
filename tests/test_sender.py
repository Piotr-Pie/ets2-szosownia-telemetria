#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test wysylki HTTP (port z client/tests/test_sender.py v0.1.3, import
dostosowany do core.ets2_core - logika BEZ ZMIAN): 202 przy poprawnym
pakiecie+tokenie+pinie, 401 zly token, 429+backoff, deduplikacja
event_id, sanitizacja revenue ujemnego."""
import sys
import os
import json
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import TelemetrySender, ApiError, FatalAuthError, EventTracker  # noqa: E402
from _tls_test_utils import (  # noqa: E402
    generate_self_signed_cert, sha256_hex_of_cert, start_https_server,
)

VALID_TOKEN = "test-token-abc123"
PORT = 18865

state = {
    "received": [],
    "seen_event_ids": set(),
    "force_429_count": 0,
    "dedup_hits": 0,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        if self.path != "/api/telemetry/v1/ingest":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "")

        if token != VALID_TOKEN:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"invalid token"}')
            return

        if state["force_429_count"] > 0:
            state["force_429_count"] -= 1
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"rate limited"}')
            return

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        for ev in data.get("events", []):
            eid = ev["event_id"]
            if eid in state["seen_event_ids"]:
                state["dedup_hits"] += 1
                continue
            state["seen_event_ids"].add(eid)

        state["received"].append(data)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def main():
    FAIL = 0
    tmpdir = tempfile.mkdtemp(prefix="ets2exe-tls-test-")
    try:
        cert_path, key_path = generate_self_signed_cert(tmpdir)
        pin_hex = sha256_hex_of_cert(cert_path)
        srv = start_https_server(Handler, PORT, cert_path, key_path)
        time.sleep(0.2)
        base_url = f"https://127.0.0.1:{PORT}"

        sender_ok = TelemetrySender(base_url, VALID_TOKEN, tls_sha256_pin=pin_hex)
        packet = {
            "v": 1,
            "client": {"name": "ets2-telemetry-client", "version": "0.2.0"},
            "sent_at": "2026-11-09T19:55:00.123Z",
            "game": {"running": True, "connected": True, "paused": False},
            "truck": {
                "speed_kmh": 87.4, "rpm": 1450.0, "gear": 7,
                "fuel_l": 310.5, "fuel_capacity_l": 400.0, "odometer_km": 12345.6,
            },
        }
        status = sender_ok.send(packet)
        ok = status == 202
        print(f"[{'OK ' if ok else 'FAIL'}] test1 202 poprawny pakiet (https+pin): status={status}")
        FAIL += 0 if ok else 1

        sender_bad = TelemetrySender(base_url, "zly-token", tls_sha256_pin=pin_hex)
        try:
            sender_bad.send(packet)
            print("[FAIL] test2: oczekiwano FatalAuthError")
            FAIL += 1
        except FatalAuthError as e:
            print(f"[OK ] test2 401 zly token -> FatalAuthError: {e}")

        state["force_429_count"] = 1
        try:
            sender_ok.send(packet)
            print("[FAIL] test3: oczekiwano ApiError HTTP 429")
            FAIL += 1
        except ApiError as e:
            ok = "429" in str(e)
            print(f"[{'OK ' if ok else 'FAIL'}] test3 429 -> ApiError: {e}")
            FAIL += 0 if ok else 1
            t0 = time.monotonic()
            sender_ok.backoff_sleep()
            dt = time.monotonic() - t0
            ok2 = dt >= 0.9
            print(f"[{'OK ' if ok2 else 'FAIL'}] test3b backoff_sleep trwał {dt:.2f}s (oczekiwano >=~1s)")
            FAIL += 0 if ok2 else 1
        status2 = sender_ok.send(packet)
        ok3 = status2 == 202
        print(f"[{'OK ' if ok3 else 'FAIL'}] test3c ponowienie po 429 -> 202: status={status2}")
        FAIL += 0 if ok3 else 1

        tracker = EventTracker()
        parsed_before = {
            "job_delivered_flag": False, "job_delivered_distance_km": 412.3,
            "job_delivered_earned_xp": 1500, "job_delivered_delivery_time": 999,
            "job_delivered_revenue": 18450,
        }
        parsed_after = dict(parsed_before, job_delivered_flag=True)
        ev1 = tracker.check(parsed_before)
        ev2 = tracker.check(parsed_after)
        ev3 = tracker.check(parsed_before)
        print(f"ev1={ev1} ev2={ev2} ev3={ev3}")
        ok4 = ev1 is None and ev2 is not None and ev2["type"] == "job_delivered"
        print(f"[{'OK ' if ok4 else 'FAIL'}] test4a wykrycie zdarzenia na krawędzi: {ok4}")
        FAIL += 0 if ok4 else 1

        ok4b = ev2 is not None and ev2.get("revenue") == 18450
        print(f"[{'OK ' if ok4b else 'FAIL'}] test4b_revenue revenue w zdarzeniu: {ev2.get('revenue') if ev2 else None}")
        FAIL += 0 if ok4b else 1

        packet_ev = dict(packet)
        packet_ev["events"] = [ev2]
        sender_ok.send(packet_ev)
        sender_ok.send(packet_ev)
        ok5 = state["dedup_hits"] >= 1
        print(f"[{'OK ' if ok5 else 'FAIL'}] test4c serwer wykrył duplikat event_id: dedup_hits={state['dedup_hits']}")
        FAIL += 0 if ok5 else 1

        tracker_neg = EventTracker()
        parsed_before_neg = {
            "job_delivered_flag": False, "job_delivered_distance_km": 100.0,
            "job_delivered_earned_xp": 500, "job_delivered_delivery_time": 1234,
            "job_delivered_revenue": -999,
        }
        parsed_after_neg = dict(parsed_before_neg, job_delivered_flag=True)
        tracker_neg.check(parsed_before_neg)
        ev_neg = tracker_neg.check(parsed_after_neg)
        ok6 = ev_neg is not None and ev_neg["revenue"] == 0
        print(f"[{'OK ' if ok6 else 'FAIL'}] test5 revenue ujemny -> wysłano revenue={ev_neg['revenue'] if ev_neg else None}")
        FAIL += 0 if ok6 else 1

        print()
        print(f"Pakietów odebranych przez serwer testowy: {len(state['received'])}")
        if FAIL:
            print(f"WYNIK: {FAIL} testów nieudanych")
            sys.exit(1)
        print("WYNIK: wszystkie testy wysyłki HTTP (core.ets2_core) przeszły")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
