#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testy przypinania certyfikatu (port z client/tests/test_tls_pin.py
v0.1.3, import dostosowany do core.ets2_core - logika BEZ ZMIAN)."""
import io
import sys
import os
import shutil
import tempfile
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ets2_core import (  # noqa: E402
    TelemetrySender, ApiError, CertPinMismatchError, validate_server_url,
)
from _tls_test_utils import (  # noqa: E402
    generate_self_signed_cert, sha256_hex_of_cert, start_https_server,
)

TOKEN = "super-secret-token-NIE-WYPISYWAC-123"
PORT = 18866

received = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        received.append(self.headers.get("Authorization", ""))
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


PACKET = {
    "v": 1,
    "client": {"name": "ets2-telemetry-client", "version": "0.2.0"},
    "sent_at": "2026-11-09T20:00:00.000Z",
    "game": {"running": True, "connected": True, "paused": False},
}


def main():
    FAIL = 0
    all_output = io.StringIO()
    tmpdir = tempfile.mkdtemp(prefix="ets2exe-tls-pin-test-")
    srv = None
    try:
        cert_a, key_a = generate_self_signed_cert(tmpdir, cn="server-a")
        pin_a = sha256_hex_of_cert(cert_a)
        srv = start_https_server(Handler, PORT, cert_a, key_a)
        time.sleep(0.2)
        base_url = f"https://127.0.0.1:{PORT}"

        received.clear()
        sender = TelemetrySender(base_url, TOKEN, tls_sha256_pin=pin_a)
        status = sender.send(PACKET)
        ok1 = status == 202 and len(received) == 1
        msg = f"[{'OK ' if ok1 else 'FAIL'}] test1 pin zgodny -> status={status}, requestow_na_serwerze={len(received)}"
        print(msg); all_output.write(msg + "\n")
        FAIL += 0 if ok1 else 1

        received.clear()
        wrong_pin = "0" * 64
        sender_wrong = TelemetrySender(base_url, TOKEN, tls_sha256_pin=wrong_pin)
        try:
            sender_wrong.send(PACKET)
            msg = "[FAIL] test2: oczekiwano CertPinMismatchError"
            FAIL += 1
        except CertPinMismatchError as e:
            readable = "nie zgadza sie z tls_sha256_pin" in str(e)
            no_request_reached_server = len(received) == 0
            ok2 = readable and no_request_reached_server
            msg = (f"[{'OK ' if ok2 else 'FAIL'}] test2 pin niezgodny -> "
                   f"CertPinMismatchError: {e!r}, requestow_na_serwerze={len(received)}")
            FAIL += 0 if ok2 else 1
        print(msg); all_output.write(msg + "\n")

        received.clear()
        sender_nopin = TelemetrySender(base_url, TOKEN, tls_sha256_pin=None)
        try:
            sender_nopin.send(PACKET)
            msg = "[FAIL] test3: oczekiwano ApiError (weryfikacja CA self-signed)"
            FAIL += 1
        except ApiError as e:
            is_cert_error = "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e).lower()
            ok3 = is_cert_error and len(received) == 0
            msg = f"[{'OK ' if ok3 else 'FAIL'}] test3 brak pinu, self-signed -> ApiError (CA): {e}"
            FAIL += 0 if ok3 else 1
        print(msg); all_output.write(msg + "\n")

        try:
            TelemetrySender("http://127.0.0.1:9999", TOKEN, tls_sha256_pin=pin_a)
            msg = "[FAIL] test4: oczekiwano ValueError dla http://"
            FAIL += 1
        except ValueError as e:
            ok4 = "https" in str(e).lower()
            msg = f"[{'OK ' if ok4 else 'FAIL'}] test4 http:// odrzucone -> ValueError: {e}"
            FAIL += 0 if ok4 else 1
        print(msg); all_output.write(msg + "\n")

        bad_urls = [
            f"https://127.0.0.1:{PORT}/x?a=1",
            f"https://127.0.0.1:{PORT}/x#frag",
        ]
        ok5 = True
        for u in bad_urls:
            try:
                validate_server_url(u)
                ok5 = False
                msg = f"[FAIL] test5: oczekiwano ValueError dla {u!r}"
            except ValueError as e:
                msg = f"[OK ] test5 odrzucono {u!r}: {e}"
            print(msg); all_output.write(msg + "\n")
        FAIL += 0 if ok5 else 1

        srv.shutdown()
        srv.server_close()
        cert_b, key_b = generate_self_signed_cert(tmpdir, cn="server-b")
        pin_b = sha256_hex_of_cert(cert_b)
        assert pin_a != pin_b, "certyfikaty testowe musza sie roznic"
        srv = start_https_server(Handler, PORT, cert_b, key_b)
        time.sleep(0.3)
        received.clear()
        try:
            sender.send(PACKET)
            msg = "[FAIL] test6: oczekiwano CertPinMismatchError po wymianie certyfikatu serwera"
            FAIL += 1
        except CertPinMismatchError as e:
            ok6 = len(received) == 0
            msg = (f"[{'OK ' if ok6 else 'FAIL'}] test6 pin sprawdzany na kazdym "
                   f"polaczeniu -> CertPinMismatchError: {e}")
            FAIL += 0 if ok6 else 1
        print(msg); all_output.write(msg + "\n")
        received.clear()
        sender_b = TelemetrySender(base_url, TOKEN, tls_sha256_pin=pin_b)
        status_b = sender_b.send(PACKET)
        ok6b = status_b == 202 and len(received) == 1
        msg = f"[{'OK ' if ok6b else 'FAIL'}] test6b nowy pin (pin_b) do nowego certu -> status={status_b}"
        print(msg); all_output.write(msg + "\n")
        FAIL += 0 if ok6b else 1

        captured = all_output.getvalue()
        ok7 = TOKEN not in captured
        msg = f"[{'OK ' if ok7 else 'FAIL'}] test7 token nie wystepuje w zebranym outputie testow: {ok7}"
        print(msg)
        FAIL += 0 if ok7 else 1

        print()
        if FAIL:
            print(f"WYNIK: {FAIL} testów nieudanych")
            sys.exit(1)
        print("WYNIK: wszystkie testy przypinania certyfikatu (core.ets2_core) przeszły")
    finally:
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
