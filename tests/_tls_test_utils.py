#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pomocnicze funkcje TYLKO dla testow (nie wchodzi do paczki ZIP):
generowanie samopodpisanego certyfikatu (openssl CLI) w katalogu
tymczasowym i uruchamianie lokalnego serwera HTTPS z tym certyfikatem,
do testowania przypinania certyfikatu (tls_sha256_pin) klienta."""
import hashlib
import ssl
import subprocess
import threading
from http.server import HTTPServer


def generate_self_signed_cert(tmpdir: str, cn: str = "127.0.0.1"):
    """Generuje samopodpisany certyfikat RSA 2048 + klucz w tmpdir
    (katalog testowy, NIGDY w paczce). Zwraca (cert_path, key_path)."""
    key_path = f"{tmpdir}/key.pem"
    cert_path = f"{tmpdir}/cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_path, "-out", cert_path,
            "-days", "1", "-nodes", "-subj", f"/CN={cn}",
        ],
        check=True, capture_output=True,
    )
    return cert_path, key_path


def sha256_hex_of_cert(cert_path: str) -> str:
    """SHA-256 (hex) certyfikatu w formie DER - identyczne z tym, co liczy
    klient (hashlib.sha256(getpeercert(binary_form=True)))."""
    der = subprocess.run(
        ["openssl", "x509", "-in", cert_path, "-outform", "DER"],
        check=True, capture_output=True,
    ).stdout
    return hashlib.sha256(der).hexdigest()


class _QuietHTTPServer(HTTPServer):
    """Jak HTTPServer, ale nie wypisuje tracebacku na stderr, gdy klient
    testowy zrywa polaczenie TLS celowo (np. po wykryciu niezgodnego
    pinu certyfikatu) - to oczekiwane zachowanie testu, nie usterka."""

    def handle_error(self, request, client_address):
        pass


def start_https_server(handler_cls, port: int, cert_path: str, key_path: str):
    """Startuje HTTPServer owiniety TLS-em (self-signed) w tle (daemon
    thread). Zwraca obiekt serwera (do .shutdown() na koniec testu)."""
    httpd = _QuietHTTPServer(("127.0.0.1", port), handler_cls)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
