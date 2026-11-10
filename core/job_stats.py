#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - akumulator statystyk zlecenia (job_stats), v0.2.5
====================================================================
Kontrakt v4 (docs/telemetry-contract-v4.md, S2): dopisuje do zdarzenia
job_delivered pola max_speed_kmh, moving_time_s, avg_speed_kmh,
fuel_used_l, avg_consumption_l_per_100km.

ZASADY (zlecenie koordynatora, v0.2.5):
- start: pierwszy pakiet z onJob=True (i connected=True) -> reset calego
  akumulatora (start_if_needed);
- kazda probka (sample): dt = czas od poprzedniej probki (zegar
  monotoniczny, injectowalny w testach), przyciety do max 2s - po pauzie
  (np. menu gry) nie dolicza sie cala przerwa;
- moving_time_s += dt, GDY speed_kmh >= 1 km/h;
- max_speed_kmh = max(dotychczasowy, probka), PRZYCIETE do 200 (kazda
  probka jest capowana do 200 PRZED wejsciem do max - tak samo jak
  wymaga kontrakt dla pola w zdarzeniu);
- fuel_used_l += max(0, fuel_poprzednia - fuel_teraz); WZROSTY
  (tankowanie) sa IGNOROWANE (nie odejmowane od sumy, nie zerowane);
- koniec przez dostawe: finish_delivery(distance_km) liczy
  avg_speed_kmh = distance_km / (moving_time_s/3600) (None gdy
  moving_time_s == 0) i avg_consumption_l_per_100km =
  fuel_used_l / distance_km * 100 (None gdy distance_km < 0.5), POTEM
  resetuje akumulator;
- koniec bez dostawy (rozlaczenie / zmiana / anulowanie zlecenia):
  abort() zeruje akumulator i NIC nie zwraca - wolajacy (EventTracker w
  core/ets2_core.py) nic nie wysyla w tym przypadku.

SANITIZACJA PROBKI (wartosci ujemne/NaN/inf "nie zasmiecaj sum"):
- speed_kmh: NaN/inf/ujemna -> TRAKTOWANA JAK 0 dla tej probki (ten tick
  wyglada jak "stoi w miejscu" - nie psuje sum, speed_kmh jest wielkoscia
  chwilowa, 0 jest neutralne).
- fuel_l: NaN/inf/ujemna -> PROBKA POMIJANA dla delty paliwa (poprzedni
  WAZNY odczyt paliwa zostaje jako baza do kolejnej delty). UWAGA:
  fuel_l to wielkosc ZAPASU (stock), nie szybkosc (rate) - dosłowne
  "traktuj jak 0" zrobiloby z jednej zlej probki falszywy ogromny spadek
  (poprzedni_fuel - 0 = caly bak zuzyty w jednej probce). Pominiecie
  probki jest bezpieczniejsza realizacja tej samej intencji ("nie
  zasmiecaj sum") - patrz raport client-exe-v0.2.5.md.
"""
from __future__ import annotations

import math
import time

MAX_SAMPLE_DT_S = 2.0
MAX_SPEED_KMH_CAP = 200.0
MOVING_SPEED_THRESHOLD_KMH = 1.0
MIN_DISTANCE_KM_FOR_CONSUMPTION = 0.5


def _sanitize_speed_for_sample(speed_kmh: float) -> float:
    """NaN/inf/ujemna -> 0.0 (patrz docstring modulu)."""
    if not math.isfinite(speed_kmh) or speed_kmh < 0:
        return 0.0
    return speed_kmh


class JobStatsAccumulator:
    """Jeden akumulator per zlecenie. Wolany z EventTracker w
    core/ets2_core.py - patrz tam integracja z petla wysylkowa."""

    def __init__(self):
        self.active = False
        self.moving_time_s = 0.0
        self.max_speed_kmh = 0.0
        self.fuel_used_l = 0.0
        self._last_sample_time: float | None = None
        self._last_valid_fuel_l: float | None = None

    def reset(self) -> None:
        self.active = False
        self.moving_time_s = 0.0
        self.max_speed_kmh = 0.0
        self.fuel_used_l = 0.0
        self._last_sample_time = None
        self._last_valid_fuel_l = None

    def start_if_needed(self, on_job: bool) -> None:
        """Wolac na KAZDEJ probce, gdy connected=True. Pierwsza probka z
        on_job=True (gdy akumulator nieaktywny) zeruje wszystko i startuje
        liczenie od nowa."""
        if on_job and not self.active:
            self.reset()
            self.active = True

    def abort(self) -> None:
        """Rozlaczenie (connected=False) ALBO on_job=False bez wczesniej
        wykrytej dostawy (zmiana/anulowanie zlecenia): zeruje akumulator,
        NIC nie zwraca - wolajacy nic nie wysyla."""
        if self.active:
            self.reset()

    def sample(self, speed_kmh: float, fuel_l: float, now: float | None = None) -> None:
        """Wolac tylko gdy self.active (po start_if_needed). `now` -
        time.monotonic() injectowalne dla testow syntetycznych."""
        if not self.active:
            return
        if now is None:
            now = time.monotonic()

        speed = _sanitize_speed_for_sample(speed_kmh)
        capped_speed = min(speed, MAX_SPEED_KMH_CAP)
        self.max_speed_kmh = max(self.max_speed_kmh, capped_speed)

        if self._last_sample_time is not None:
            dt = now - self._last_sample_time
            if not math.isfinite(dt) or dt < 0:
                dt = 0.0
            dt = min(dt, MAX_SAMPLE_DT_S)
            if speed >= MOVING_SPEED_THRESHOLD_KMH:
                self.moving_time_s += dt
        self._last_sample_time = now

        fuel_valid = math.isfinite(fuel_l) and fuel_l >= 0
        if fuel_valid:
            if self._last_valid_fuel_l is not None:
                drop = self._last_valid_fuel_l - fuel_l
                if drop > 0:
                    self.fuel_used_l += drop
            self._last_valid_fuel_l = fuel_l
        # probka z nieprawidlowym fuel_l: pomijamy (patrz docstring modulu)

    def finish_delivery(self, distance_km: float) -> dict:
        """Wolac, gdy EventTracker wykryl job_delivered. Zwraca 5 pol z
        kontraktu v4 (S2) do dopisania do zdarzenia i resetuje akumulator
        (gotowy na kolejne zlecenie)."""
        moving_time_s_int = int(round(self.moving_time_s))
        if moving_time_s_int > 0:
            avg_speed = distance_km / (moving_time_s_int / 3600.0)
            avg_speed = min(max(avg_speed, 0.0), MAX_SPEED_KMH_CAP)
        else:
            avg_speed = None

        if distance_km < MIN_DISTANCE_KM_FOR_CONSUMPTION:
            avg_consumption = None
        else:
            avg_consumption = (self.fuel_used_l / distance_km) * 100.0

        result = {
            "max_speed_kmh": round(min(self.max_speed_kmh, MAX_SPEED_KMH_CAP), 1),
            "moving_time_s": moving_time_s_int,
            "avg_speed_kmh": round(avg_speed, 1) if avg_speed is not None else None,
            "fuel_used_l": round(max(self.fuel_used_l, 0.0), 2),
            "avg_consumption_l_per_100km": (
                round(avg_consumption, 1) if avg_consumption is not None else None
            ),
        }
        self.reset()
        return result
