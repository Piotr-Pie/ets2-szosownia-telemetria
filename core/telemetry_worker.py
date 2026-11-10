#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - watek wysylkowy z pelnym gatingiem (v0.2.6, kontrakt v5)
===========================================================================

NOWY MODUL. Wydzielony z app.py (tam wczesniej TelemetryWorker byl
klasa wewnetrzna) - zeby dalo sie go przetestowac BEZ tkinter/pystray,
analogicznie do core/job_stats.py i core/window_controller.py (patrz
tests/test_telemetry_worker.py).

PRZYCZYNA BLEDU NAPRAWIANEGO W TEJ WERSJI (zgloszenie wlasciciela,
zrzut ekranu z 2026-11-10): w v0.2.3-0.2.5 "Wstrzymaj wysylke" z menu
zasobnika wywolywalo App.on_stop() -> TelemetryWorker.stop() (app.py,
STARA wersja, linia ok. 168: `def stop(self): self._stop_event.set()`).
Watek `_run()` sprawdzal `stop_event.is_set()` TYLKO na poczatku
glownej petli `while` (stara linia 177) - jesli w momencie klikniecia
"Wstrzymaj" watek byl w trakcie draza bufora (`while buffer: ...
self._sender.send(pkt)`, stara linia 218-241) albo w `backoff_sleep()`
(`time.sleep()`, NIE sprawdza stop_event), DOKANCZAL caly biezacy
przebieg - w tym mogl wyslac WIELE zalegajacych w buforze pakietow
(np. pakiet connected=false/heartbeat z poprzedniej iteracji) zanim
faktycznie przerwal petle. Co gorsza - KAZDE kolejne "Wznow wysylke"
(app.py, stara `on_save_and_start()`, linia 469) tworzylo CALKIEM NOWY
obiekt `TelemetryWorker` i NOWY watek, NIE czekajac na zakonczenie
poprzedniego - przy kilku cyklach pauza/wznow w krotkim czasie moglo
to zostawic "zombie" watki nadal czytajace pamiec i wysylajace pakiety
w tle, kompletnie niewidoczne dla UI (ktore znalo tylko NAJNOWSZY
`self.worker`). To tlumaczy zrzut wlasciciela: menu pokazywalo "Wznow
wysylke" (a wiec UI myslalo, ze jest wstrzymane), a serwer nadal
dostawal pakiety co ~2s.

NAPRAWA (ten modul): JEDEN dlugozyjacy watek (`start()` wywolywane raz),
ktory WCALE nie konczy sie przy pauzie - zamiast tego `pause()`/
`resume()` ustawiaja flage sprawdzana NA POCZATKU KAZDEGO ticku
(`tick()`), PRZED jakimkolwiek odczytem pamieci/wyslaniem. Bufor jest
czyszczony przy KAZDYM wejsciu w stan wstrzymany (recznie i
automatycznie) - zero szans na wyslanie zaleglych pakietow po
wznowieniu. `tick()` jest publiczna metoda (bez petli/sleep) wlasnie
po to, zeby testy mogly wolac ja wielokrotnie z atrapami (bez
prawdziwych watkow/czasu) i symulowac dowolnie dlugi czas.

STANY (kontrakt v5, docs/telemetry-contract-v5.md SS1):
  - aktywna:                   manual_paused=False, auto_paused=False
  - wstrzymana przez gracza:   manual_paused=True  (WYGRYWA z automatem)
  - automatycznie wstrzymana:  manual_paused=False, auto_paused=True
    (tylko gdy game_gate_enabled_fn() == True ORAZ proces gry nie dziala)

W STANACH "wstrzymana"/"automatycznie wstrzymana" `tick()` konczy sie
NATYCHMIAST na samej gorze - zero odczytu pamieci (self._reader.read()
NIE jest wolane), zero sieci (self._sender.send() NIE jest wolane).

BASELINE (kontrakt v5 SS3): kazde wyjscie ze stanu wstrzymanego (manual
pause -> resume() ORAZ automatyczne auto_paused=False po powrocie gry)
ustawia `_pending_baseline = True` - pierwszy PAKIET ZBUDOWANY po tym
(niezaleznie od tego czy connected) dostaje `"baseline": True"
(build_packet, core/ets2_core.py) i flaga jest czyszczona. Watek
ZAWSZE zaczyna w stanie wstrzymanym przez gracza (manual_paused=True w
konstruktorze) - start z autostartu (wariant B, 0.2.3) bez zmian: nikt
nie wola resume() automatycznie.

ZEROWANIE STATYSTYK ZLECENIA (kontrakt v5 SS2, dawniej SS2 kontraktu v4):
kazde wejscie w stan wstrzymany (recznie i automatycznie) wola
EventTracker.reset_for_pause() (core/ets2_core.py) - zeruje akumulator
JobStatsAccumulator ORAZ resetuje punkt odniesienia detekcji krawedzi
jobDelivered (zeby dostawa "niewidziana" w czasie wstrzymania nie
wygenerowala falszywego zdarzenia po wznowieniu).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from core.ets2_core import (
    BUFFER_WINDOW_S,
    CLIENT_NAME,
    CLIENT_VERSION,
    SERVER_URL,
    SEND_INTERVAL_CONNECTED,
    SEND_INTERVAL_DISCONNECTED,
    ApiError,
    CertPinMismatchError,
    EventTracker,
    FatalAuthError,
    SharedMemoryReader,
    TelemetrySender,
    build_packet,
    is_game_process_running,
    mem_error_status_line,
    safe_parse_telemetry,
    safe_read_memory,
    status_line,
)

TOKEN_REJECTED_MSG = "Token odrzucony — wygeneruj nowy na szosownia.com/konto"

# Co ile sekund watek "budzi sie" w stanie wstrzymanym - zeby pause()/
# resume() wywolane z GUI zadzialaly z malym opoznieniem (nie wiecej
# niz ta wartosc), bez zadnego odczytu/sieci w miedzyczasie.
PAUSE_POLL_INTERVAL = 1.0

# Kontrakt v5 SS1: "tylko sprawdzanie procesu, co 2-5 s" w stanie
# automatycznie wstrzymanym.
AUTO_POLL_INTERVAL = 3.0

STATUS_ACTIVE = "wysyłka aktywna"
STATUS_MANUAL_PAUSED = "wstrzymana przez gracza"
STATUS_AUTO_PAUSED = "czeka na uruchomienie gry"


class TelemetryWorker:
    """Petla wysylkowa z pelnym gatingiem (manual pause + auto pause wg
    stanu procesu gry). Jeden watek na cale zycie aplikacji (od pierwszego
    `start()` az do `stop()` przy zamknieciu) - pauza/wznowienie NIGDY
    nie tworzy/niszczy watku, tylko przelacza flagi sprawdzane w `tick()`.
    """

    def __init__(
        self,
        token: str,
        tls_sha256_pin: str | None,
        on_status: Callable[[str], None],
        on_tooltip: Callable[[str], None] | None = None,
        reader=None,
        sender=None,
        tracker: EventTracker | None = None,
        process_checker: Callable[[], bool] | None = None,
        game_gate_enabled_fn: Callable[[], bool] | None = None,
    ):
        self._sender = sender or TelemetrySender(SERVER_URL, token, tls_sha256_pin)
        self._reader = reader or SharedMemoryReader()
        self._tracker = tracker or EventTracker()
        self._process_checker = process_checker or is_game_process_running
        self._game_gate_enabled_fn = game_gate_enabled_fn or (lambda: True)
        self._on_status = on_status
        self._on_tooltip = on_tooltip or (lambda text: None)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._buffer: deque = deque()

        # Wariant B (0.2.3, BEZ ZMIAN): watek ZAWSZE zaczyna wstrzymany
        # przez gracza - trzeba jawnie wywolac resume().
        self._manual_paused = True
        self._auto_paused = False
        self._pending_baseline = True

        self._last_state = None
        self._last_mem_error = None

    # -- stan (odczyt z GUI, np. etykieta menu zasobnika) -------------

    @property
    def manual_paused(self) -> bool:
        return self._manual_paused

    @property
    def auto_paused(self) -> bool:
        return self._auto_paused

    @property
    def sending_paused(self) -> bool:
        """Suma (manual LUB auto) - do etykiety menu zasobnika, patrz
        kontrakt v5 SS1 tabela, kolumna 'Menu zasobnika'."""
        return self._manual_paused or self._auto_paused

    def status_text(self) -> str:
        """Dokladnie jeden z 3 tekstow z kontraktu v5 SS1 (tooltip ikony)."""
        if self._manual_paused:
            return STATUS_MANUAL_PAUSED
        if self._auto_paused:
            return STATUS_AUTO_PAUSED
        return STATUS_ACTIVE

    def _emit_tooltip(self) -> None:
        self._on_tooltip(self.status_text())

    # -- sterowanie ----------------------------------------------------

    def start(self) -> None:
        """Startuje watek w tle (jednorazowo) - watek zaczyna wstrzymany,
        az do pierwszego resume()."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_forever, daemon=True)
            self._thread.start()

    def update_token(self, token: str, tls_sha256_pin: str | None = None) -> None:
        """Wolac, gdy gracz zmienil token i kliknal ponownie 'Zapisz i
        uruchom' - podmienia nadawce BEZ zatrzymywania watku."""
        self._sender = TelemetrySender(SERVER_URL, token, tls_sha256_pin)

    def pause(self) -> None:
        """'Wstrzymaj wysyłkę' (recznie) - ma pierwszenstwo nad automatem
        (kontrakt v5 SS1: 'Reczne wstrzymanie wygrywa z automatem')."""
        if not self._manual_paused:
            self._manual_paused = True
            self._buffer.clear()
            self._tracker.reset_for_pause()
            self._last_mem_error = None
            self._last_state = None
        self._emit_tooltip()
        self._on_status(self.status_text())

    def resume(self) -> None:
        """'Wznów wysyłkę' (recznie). Gdy wywolane w trakcie AUTOMATYCZNEGO
        wstrzymania (manual_paused juz False) - bezpieczny no-op (kontrakt
        v5 SS1: 'ręczne wznowienie też działa', patrz raport)."""
        if self._manual_paused:
            self._manual_paused = False
            self._pending_baseline = True
        self._emit_tooltip()
        self._on_status(self.status_text())

    def stop(self) -> None:
        """Pelne zamkniecie watku (tylko przy Zakoncz/zamknieciu programu,
        NIE przy zwyklej pauzie)."""
        self._stop_event.set()

    # -- petla -----------------------------------------------------------

    def _run_forever(self) -> None:
        self._emit_tooltip()
        self._on_status(f"{CLIENT_NAME} v{CLIENT_VERSION} - start (serwer: {SERVER_URL})")
        while not self._stop_event.is_set():
            interval = self.tick()
            self._stop_event.wait(interval)

    def _enter_auto_pause(self) -> None:
        self._auto_paused = True
        self._buffer.clear()
        self._tracker.reset_for_pause()
        self._last_mem_error = None
        self._last_state = None
        self._emit_tooltip()
        self._on_status(self.status_text())

    def _exit_auto_pause(self) -> None:
        self._auto_paused = False
        self._pending_baseline = True
        self._emit_tooltip()

    def tick(self, now: float | None = None) -> float:
        """Jedna iteracja petli - zwraca liczbe sekund do nastepnego ticku.
        Publiczna specjalnie dla testow (wolana wprost, bez watku/sleep -
        patrz tests/test_telemetry_worker.py), ktore moga symulowac
        dowolnie dlugi czas bez prawdziwego oczekiwania."""
        if self._manual_paused:
            # Kontrakt v5 SS1: ZERO odczytu pamieci, ZERO sieci.
            return PAUSE_POLL_INTERVAL

        game_process_running = self._process_checker()
        if self._game_gate_enabled_fn() and not game_process_running:
            if not self._auto_paused:
                self._enter_auto_pause()
            # Kontrakt v5 SS1: tylko sprawdzanie procesu, co 2-5 s.
            return AUTO_POLL_INTERVAL
        if self._auto_paused:
            self._exit_auto_pause()

        if now is None:
            now = time.monotonic()

        raw, mem_err = safe_read_memory(self._reader)
        parsed = None
        events: list[dict] = []

        if mem_err is None and raw is not None:
            parsed, mem_err = safe_parse_telemetry(raw)
            if mem_err is not None:
                raw = None

        if mem_err is not None:
            if mem_err != self._last_mem_error:
                self._last_mem_error = mem_err
                self._on_status(mem_error_status_line(mem_err))
        else:
            self._last_mem_error = None

        connected = raw is not None and parsed is not None
        running = game_process_running or connected

        if connected:
            ev = self._tracker.check(parsed)
            if ev:
                events.append(ev)
        else:
            # kontrakt v4/v5: rozlaczenie w trakcie zlecenia zeruje
            # akumulator statystyk dostawy, nic nie wysyla.
            self._tracker.on_disconnected()

        state = (running, connected)
        if state != self._last_state:
            self._last_state = state
            self._on_status(status_line(running, connected))

        baseline = self._pending_baseline
        if baseline:
            self._pending_baseline = False

        packet = build_packet(connected, running, parsed, events, baseline=baseline)
        self._buffer.append((now, packet))
        while self._buffer and (now - self._buffer[0][0]) > BUFFER_WINDOW_S:
            self._buffer.popleft()

        stopped = False
        while self._buffer:
            _, pkt = self._buffer[0]
            try:
                self._sender.send(pkt)
                self._buffer.popleft()
            except FatalAuthError:
                self._on_status(TOKEN_REJECTED_MSG)
                stopped = True
                break
            except CertPinMismatchError as e:
                self._on_status(f"[BŁĄD] {e}")
                stopped = True
                break
            except ApiError as e:
                msg = str(e)
                if "HTTP 400" in msg or "HTTP 413" in msg:
                    self._buffer.popleft()
                    continue
                if "HTTP 429" in msg:
                    self._on_status("[info] limit 429, czekam (backoff)")
                    self._sender.backoff_sleep()
                    break
                self._on_status(f"[info] brak sieci / błąd serwera ({msg}), buforuję")
                break

        if stopped:
            # Token odrzucony / pin niezgodny: wstrzymaj jak przy recznej
            # pauzie (gracz musi poprawic token/konfiguracje i kliknac
            # 'Wznów wysyłkę') - watek NIE jest zabijany, zeby dalo sie
            # wznowic bez restartu programu.
            self._manual_paused = True
            self._buffer.clear()
            self._emit_tooltip()
            return PAUSE_POLL_INTERVAL

        return SEND_INTERVAL_CONNECTED if connected else SEND_INTERVAL_DISCONNECTED
