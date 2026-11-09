#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - rdzen telemetrii (wspoldzielony przez CLI v0.1.x i exe v0.2.0)
================================================================================

UWAGA (2026-11-09, v0.2.0): ten plik jest PRZENIESIENIEM logiki z
client/client.py (v0.1.3) BEZ ZMIAN MERYTORYCZNYCH w: parserze pamieci,
wysylce/deduplikacji/przypinaniu TLS i poprawkach kernel32. Zgodnie ze
zleceniem koordynatora z 2026-11-09 nie zmieniono tu nic z logiki -
usunieto TYLKO funkcje specyficzne dla CLI (main() z petla + print(),
load_config() z SystemExit), ktore w kliencie .exe zastepuje GUI
(client-exe/app.py). Wszystkie testy logiki ponizej sa powtorzone w
client-exe/tests/ (zaadaptowane importy, identyczna trescia asercji co
client/tests/*.py) i przechodza - patrz raport.

Czyta pamiec wspoldzielona pluginu SCS SDK ("Local\\SCSTelemetry", 32 KB)
i wysyla snapshoty do API szosownia.com zgodnie z kontraktem:
docs/telemetry-contract-v1.md (POST {SITE_URL}/api/telemetry/v1/ingest).

Zrodlo struktury pamieci (WERYFIKOWANE w sesji v0.1.3, nie zgadywane):
  Repo:   https://github.com/truckermudgeon/scs-sdk-plugin  (fork MIT,
          upstream RenCloud/scs-sdk-plugin)
  Commit: c8910d6e9a5ca0c2fa018942054263292cab19a4
  Plik:   scs-telemetry/inc/scs-telemetry-common.hpp (struct scsTelemetryMap_s)
  Release uzyty do pobrania DLL: v1.12.1 (2025-12-19),
          asset build-windows-latest.zip -> scs-telemetry.dll

ZAROBEK (revenue), PRZYPINANIE CERTYFIKATU (tls_sha256_pin), LINIA STATUSU
i POPRAWKA KRYTYCZNA kernel32 (argtypes/restype) - patrz pelna historia i
uzasadnienie w client/client.py (v0.1.1-v0.1.3, nie duplikowane tutaj, bo
plik ten jest zamrozona kopia tej samej logiki).

POZYCJA CIĘŻARÓWKI (truck.position) - dodane 2026-11-09, v0.2.1, kontrakt v2
(docs/telemetry-contract-v2.md). Pelne uzasadnienie (numery linii w
scs-telemetry-common.hpp i scs_telemetry.cpp, commit powyzej) - patrz
docstring client/client.py (v0.1.4), sekcja "POZYCJA CIĘŻARÓWKI" - skrot:
truck_dp (ZONA 8, offset 2200), coordinateX/Y/Z = pozycja, rotationX =
heading (ulamek obrotu, *360.0 % 360.0 -> stopnie [0,360)). Przeniesione
bez zmian merytorycznych z client/client.py v0.1.4.
"""

from __future__ import annotations

import ctypes as C
import hashlib
import hmac
import http.client
import json
import math
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone

CLIENT_NAME = "ets2-telemetry-client"
CLIENT_VERSION = "0.2.1"

# commit uzyty do wyliczenia poniższych offsetow (dla audytu / aktualizacji)
HEADER_COMMIT = "c8910d6e9a5ca0c2fa018942054263292cab19a4"
HEADER_URL = (
    "https://github.com/truckermudgeon/scs-sdk-plugin/blob/"
    f"{HEADER_COMMIT}/scs-telemetry/inc/scs-telemetry-common.hpp"
)

MMF_NAME = "Local\\SCSTelemetry"
MMF_SIZE = 32 * 1024  # 32 KB, scs-telemetry-common.hpp linia 30

GAME_PROCESS_NAMES = ("eurotrucks2.exe",)

SERVER_URL = "https://szosownia.com"  # na stale, v0.2.0 - zlecenie koordynatora
ENDPOINT_PATH = "/api/telemetry/v1/ingest"

SEND_INTERVAL_CONNECTED = 0.5   # 2 Hz - kontrakt
SEND_INTERVAL_DISCONNECTED = 5.0  # heartbeat co 5 s - kontrakt
BUFFER_WINDOW_S = 60.0         # bufor 60 s przy braku sieci - kontrakt
MAX_EVENTS_PER_PACKET = 10     # kontrakt: events[] max 10 elementow
HTTP_TIMEOUT_S = 5
BACKOFF_MAX_S = 10.0


# ---------------------------------------------------------------------------
# 1) Struktura pamieci (ctypes) - mirror scsTelemetryMap_s, 1:1 z naglowkiem
#    az do strefy 12 (special_b). Strefy 13/14 (substances, trailer[10]) nie
#    sa potrzebne w v1 i nie sa modelowane. (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

class _ScsValues(C.Structure):
    _fields_ = [
        ("telemetry_plugin_revision", C.c_uint),
        ("version_major", C.c_uint),
        ("version_minor", C.c_uint),
        ("game", C.c_uint),
        ("telemetry_version_game_major", C.c_uint),
        ("telemetry_version_game_minor", C.c_uint),
    ]


class _CommonUi(C.Structure):
    _fields_ = [("time_abs", C.c_uint)]


class _ConfigUi(C.Structure):
    _fields_ = [
        ("gears", C.c_uint),
        ("gears_reverse", C.c_uint),
        ("retarderStepCount", C.c_uint),
        ("truckWheelCount", C.c_uint),
        ("selectorCount", C.c_uint),
        ("time_abs_delivery", C.c_uint),
        ("maxTrailerCount", C.c_uint),
        ("unitCount", C.c_uint),
        ("plannedDistanceKm", C.c_uint),
    ]


class _TruckUi(C.Structure):
    _fields_ = [
        ("shifterSlot", C.c_uint),
        ("retarderBrake", C.c_uint),
        ("lightsAuxFront", C.c_uint),
        ("lightsAuxRoof", C.c_uint),
        ("truck_wheelSubstance", C.c_uint * 16),
        ("hshifterPosition", C.c_uint * 32),
        ("hshifterBitmask", C.c_uint * 32),
    ]


class _GameplayUi(C.Structure):
    _fields_ = [
        ("jobDeliveredDeliveryTime", C.c_uint),
        ("jobStartingTime", C.c_uint),
        ("jobFinishedTime", C.c_uint),
    ]


class _CommonI(C.Structure):
    _fields_ = [("restStop", C.c_int)]


class _TruckI(C.Structure):
    _fields_ = [
        ("gear", C.c_int),
        ("gearDashboard", C.c_int),
        ("hshifterResulting", C.c_int * 32),
    ]


class _GameplayI(C.Structure):
    _fields_ = [("jobDeliveredEarnedXp", C.c_int)]


class _CommonF(C.Structure):
    _fields_ = [("scale", C.c_float)]


class _ConfigF(C.Structure):
    _fields_ = [
        ("fuelCapacity", C.c_float),
        ("fuelWarningFactor", C.c_float),
        ("adblueCapacity", C.c_float),
        ("adblueWarningFactor", C.c_float),
        ("airPressureWarning", C.c_float),
        ("airPressurEmergency", C.c_float),
        ("oilPressureWarning", C.c_float),
        ("waterTemperatureWarning", C.c_float),
        ("batteryVoltageWarning", C.c_float),
        ("engineRpmMax", C.c_float),
        ("gearDifferential", C.c_float),
        ("cargoMass", C.c_float),
        ("truckWheelRadius", C.c_float * 16),
        ("gearRatiosForward", C.c_float * 24),
        ("gearRatiosReverse", C.c_float * 8),
        ("unitMass", C.c_float),
    ]


class _TruckF(C.Structure):
    _fields_ = [
        ("speed", C.c_float),           # m/s - truck.speed (POTWIERDZONE)
        ("engineRpm", C.c_float),
        ("userSteer", C.c_float),
        ("userThrottle", C.c_float),
        ("userBrake", C.c_float),
        ("userClutch", C.c_float),
        ("gameSteer", C.c_float),
        ("gameThrottle", C.c_float),
        ("gameBrake", C.c_float),
        ("gameClutch", C.c_float),
        ("cruiseControlSpeed", C.c_float),
        ("airPressure", C.c_float),
        ("brakeTemperature", C.c_float),
        ("fuel", C.c_float),            # litry
        ("fuelAvgConsumption", C.c_float),
        ("fuelRange", C.c_float),
        ("adblue", C.c_float),
        ("oilPressure", C.c_float),
        ("oilTemperature", C.c_float),
        ("waterTemperature", C.c_float),
        ("batteryVoltage", C.c_float),
        ("lightsDashboard", C.c_float),
        ("wearEngine", C.c_float),
        ("wearTransmission", C.c_float),
        ("wearCabin", C.c_float),
        ("wearChassis", C.c_float),
        ("wearWheels", C.c_float),
        ("truckOdometer", C.c_float),   # km
        ("routeDistance", C.c_float),
        ("routeTime", C.c_float),
        ("speedLimit", C.c_float),
        ("truck_wheelSuspDeflection", C.c_float * 16),
        ("truck_wheelVelocity", C.c_float * 16),
        ("truck_wheelSteering", C.c_float * 16),
        ("truck_wheelRotation", C.c_float * 16),
        ("truck_wheelLift", C.c_float * 16),
        ("truck_wheelLiftOffset", C.c_float * 16),
    ]


class _GameplayF(C.Structure):
    _fields_ = [
        ("jobDeliveredCargoDamage", C.c_float),
        ("jobDeliveredDistanceKm", C.c_float),
        ("refuelAmount", C.c_float),
    ]


class _JobF(C.Structure):
    _fields_ = [("cargoDamage", C.c_float)]


class _ConfigB(C.Structure):
    _fields_ = [
        ("truckWheelSteerable", C.c_bool * 16),
        ("truckWheelSimulated", C.c_bool * 16),
        ("truckWheelPowered", C.c_bool * 16),
        ("truckWheelLiftable", C.c_bool * 16),
        ("isCargoLoaded", C.c_bool),
        ("specialJob", C.c_bool),
    ]


class _TruckB(C.Structure):
    _fields_ = [
        ("parkBrake", C.c_bool),
        ("motorBrake", C.c_bool),
        ("airPressureWarning", C.c_bool),
        ("airPressureEmergency", C.c_bool),
        ("fuelWarning", C.c_bool),
        ("adblueWarning", C.c_bool),
        ("oilPressureWarning", C.c_bool),
        ("waterTemperatureWarning", C.c_bool),
        ("batteryVoltageWarning", C.c_bool),
        ("electricEnabled", C.c_bool),
        ("engineEnabled", C.c_bool),
        ("wipers", C.c_bool),
        ("blinkerLeftActive", C.c_bool),
        ("blinkerRightActive", C.c_bool),
        ("blinkerLeftOn", C.c_bool),
        ("blinkerRightOn", C.c_bool),
        ("lightsParking", C.c_bool),
        ("lightsBeamLow", C.c_bool),
        ("lightsBeamHigh", C.c_bool),
        ("lightsBeacon", C.c_bool),
        ("lightsBrake", C.c_bool),
        ("lightsReverse", C.c_bool),
        ("lightsHazard", C.c_bool),
        ("cruiseControl", C.c_bool),
        ("truck_wheelOnGround", C.c_bool * 16),
        ("shifterToggle", C.c_bool * 2),
        ("differentialLock", C.c_bool),
        ("liftAxle", C.c_bool),
        ("liftAxleIndicator", C.c_bool),
        ("trailerLiftAxle", C.c_bool),
        ("trailerLiftAxleIndicator", C.c_bool),
    ]


class _GameplayB(C.Structure):
    _fields_ = [
        ("jobDeliveredAutoparkUsed", C.c_bool),
        ("jobDeliveredAutoloadUsed", C.c_bool),
    ]


class _SpecialB(C.Structure):
    _fields_ = [
        ("onJob", C.c_bool),
        ("jobFinished", C.c_bool),
        ("jobCancelled", C.c_bool),
        ("jobDelivered", C.c_bool),  # flaga TOGGLE (XOR) przy kazdej dostawie
        ("fined", C.c_bool),
        ("tollgate", C.c_bool),
        ("ferry", C.c_bool),
        ("train", C.c_bool),
        ("refuel", C.c_bool),
        ("refuelPayed", C.c_bool),
    ]


class _TruckDp(C.Structure):
    """ZONA 8 [2200-2299] - pozycja/orientacja ciezarowki (v0.2.1, BEZ ZMIAN
    wzgledem client/client.py v0.1.4, patrz tam po pelne uzasadnienie)."""
    _fields_ = [
        ("coordinateX", C.c_double),  # offset 2200
        ("coordinateY", C.c_double),  # offset 2208 (wysokosc)
        ("coordinateZ", C.c_double),  # offset 2216
        ("rotationX", C.c_double),    # offset 2224 = heading (ulamek obrotu)
        ("rotationY", C.c_double),    # offset 2232 = pitch
        ("rotationZ", C.c_double),    # offset 2240 = roll
    ]


class ScsTelemetryMap(C.Structure):
    # Uklad pamieci jest juz recznie wypadowany w naglowku (placeHolder /
    # buffer_* char[]), wiec pack=1 + te pola odtwarzaja DOKLADNIE
    # dokumentowane granice stref (zweryfikowano: 39, 499, 699, 1499, 1639,
    # 2299 - patrz asercje ponizej).
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        # STREFA 1 [0-39]
        ("sdkActive", C.c_bool),
        ("placeHolder", C.c_char * 3),
        ("paused", C.c_bool),
        ("placeHolder2", C.c_char * 3),
        ("time", C.c_ulonglong),
        ("simulatedTime", C.c_ulonglong),
        ("renderTime", C.c_ulonglong),
        ("multiplayerTimeOffset", C.c_longlong),
        # STREFA 2 [40-499]
        ("scs_values", _ScsValues),
        ("common_ui", _CommonUi),
        ("config_ui", _ConfigUi),
        ("truck_ui", _TruckUi),
        ("gameplay_ui", _GameplayUi),
        ("buffer_ui", C.c_char * 48),
        # STREFA 3 [500-699]
        ("common_i", _CommonI),
        ("truck_i", _TruckI),
        ("gameplay_i", _GameplayI),
        ("buffer_i", C.c_char * 56),
        # STREFA 4 [700-1499]
        ("common_f", _CommonF),
        ("config_f", _ConfigF),
        ("truck_f", _TruckF),
        ("gameplay_f", _GameplayF),
        ("job_f", _JobF),
        ("buffer_f", C.c_char * 28),
        # STREFA 5 [1500-1639]
        ("config_b", _ConfigB),
        ("truck_b", _TruckB),
        ("gameplay_b", _GameplayB),
        ("buffer_b2", C.c_char * 25),
        # (strefy 6-7 pominiete - nieuzywane, wypelniacz do startu zony 8)
        ("_skip_zones_6_to_7", C.c_char * (2200 - 1640)),
        # STREFA 8 [2200-2299] - pozycja/orientacja ciezarowki, v0.2.1
        ("truck_dp", _TruckDp),
        ("_skip_rest_zone8_and_zones_9_10", C.c_char * (4208 - 2248)),
        # STREFA 11 [4200-4299] - tylko pole revenue nas interesuje w v1;
        # offset 4208 = 4200 (start zony) + 8 (jobCancelledPenalty, ll)
        ("jobDeliveredRevenue_raw", C.c_longlong),  # gameplay_ll.jobDeliveredRevenue, s64
        ("_skip_rest_of_zone_11", C.c_char * (4300 - 4216)),
        # STREFA 12 [4300-4399]
        ("special_b", _SpecialB),
    ]


# Self-check wykonywany przy imporcie modulu: offsety musza sie zgadzac z
# wyliczeniem z naglowka.
assert ScsTelemetryMap.jobDeliveredRevenue_raw.offset == 4208, (
    "jobDeliveredRevenue_raw ma zly offset w ScsTelemetryMap - sprawdz "
    "layout wzgledem scs-telemetry-common.hpp (11. ZONA, offset 4208)"
)
assert ScsTelemetryMap.truck_dp.offset == 2200, (
    "truck_dp ma zly offset w ScsTelemetryMap - sprawdz layout wzgledem "
    "scs-telemetry-common.hpp (8. ZONA, offset 2200, L486-499)"
)
assert ScsTelemetryMap.truck_dp.offset + _TruckDp.rotationX.offset == 2224, (
    "truck_dp.rotationX (heading) ma zly offset - oczekiwano 2224 "
    "(2200 + 3*8, po coordinateX/Y/Z)"
)


# ---------------------------------------------------------------------------
# 2) Parser - CZYSTA funkcja: bytes -> dict. (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

def parse_telemetry(raw: bytes) -> dict:
    """Parsuje surowe bajty pamieci SCS (>= sizeof(ScsTelemetryMap)) na dict.

    Nie wykonuje konwersji jednostek (speed_kmh itp.) - to robi build_packet().
    """
    needed = C.sizeof(ScsTelemetryMap)
    if len(raw) < needed:
        raise ValueError(
            f"za mało bajtów: dostałem {len(raw)}, potrzebuję {needed}"
        )
    m = ScsTelemetryMap.from_buffer_copy(raw[:needed])
    return {
        "sdk_active": bool(m.sdkActive),
        "paused": bool(m.paused),
        "gear": int(m.truck_i.gear),
        "speed_mps": float(m.truck_f.speed),
        "engine_rpm": float(m.truck_f.engineRpm),
        "fuel_l": float(m.truck_f.fuel),
        "fuel_capacity_l": float(m.config_f.fuelCapacity),
        "odometer_km": float(m.truck_f.truckOdometer),
        "job_delivered_flag": bool(m.special_b.jobDelivered),
        "job_delivered_distance_km": float(m.gameplay_f.jobDeliveredDistanceKm),
        "job_delivered_earned_xp": int(m.gameplay_i.jobDeliveredEarnedXp),
        "job_delivered_delivery_time": int(m.gameplay_ui.jobDeliveredDeliveryTime),
        "job_delivered_revenue": int(m.jobDeliveredRevenue_raw),
        "pos_x": float(m.truck_dp.coordinateX),
        "pos_y": float(m.truck_dp.coordinateY),
        "pos_z": float(m.truck_dp.coordinateZ),
        "heading_fraction": float(m.truck_dp.rotationX),
    }


# ---------------------------------------------------------------------------
# 2b) Pozycja ciężarówki (truck.position, kontrakt v2) - BEZ ZMIAN wzgledem
#     client/client.py v0.1.4.
# ---------------------------------------------------------------------------

def build_position(parsed: dict) -> dict | None:
    """Zwraca {"x","y","z","heading_deg"} albo None, gdy odczyt pozycji z
    pamieci SCS jest niewiarygodny (NaN/+-inf w x, y, z lub heading)."""
    x = parsed["pos_x"]
    y = parsed["pos_y"]
    z = parsed["pos_z"]
    heading_fraction = parsed["heading_fraction"]
    if not all(math.isfinite(v) for v in (x, y, z, heading_fraction)):
        return None
    heading_deg = (heading_fraction * 360.0) % 360.0
    return {
        "x": x,
        "y": y,
        "z": z,
        "heading_deg": round(heading_deg, 1),
    }


# ---------------------------------------------------------------------------
# 3) Odczyt pamieci wspoldzielonej (Windows only, WinAPI przez ctypes)
#    (BEZ ZMIAN wzgledem v0.1.3, wraz z poprawka kernel32 argtypes/restype)
# ---------------------------------------------------------------------------

FILE_MAP_READ = 0x0004

INVALID_HANDLE_VALUE = C.c_void_p(-1).value


class _PROCESSENTRY32(C.Structure):
    """Uzywana przez is_game_process_running() (Toolhelp32, ANSI - stad
    Process32First/Process32Next, NIE wersje W; szExeFile jest char[260],
    nie wchar_t[260])."""
    _fields_ = [
        ("dwSize", C.c_uint32),
        ("cntUsage", C.c_uint32),
        ("th32ProcessID", C.c_uint32),
        ("th32DefaultHeapID", C.POINTER(C.c_ulong)),
        ("th32ModuleID", C.c_uint32),
        ("cntThreads", C.c_uint32),
        ("th32ParentProcessID", C.c_uint32),
        ("pcPriClassBase", C.c_long),
        ("dwFlags", C.c_uint32),
        ("szExeFile", C.c_char * 260),
    ]


def _configure_kernel32(kernel32) -> None:
    """Ustawia jawnie argtypes i restype dla WSZYSTKICH funkcji kernel32
    uzywanych w tym pliku. POPRAWKA KRYTYCZNA z v0.1.3 - przeniesiona bez
    zmian (patrz client/client.py dla pelnego uzasadnienia)."""
    if getattr(kernel32, "_ets2_winapi_configured", False):
        return

    kernel32.OpenFileMappingW.argtypes = (C.c_uint32, C.c_int, C.c_wchar_p)
    kernel32.OpenFileMappingW.restype = C.c_void_p

    kernel32.MapViewOfFile.argtypes = (
        C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_size_t,
    )
    kernel32.MapViewOfFile.restype = C.c_void_p

    kernel32.UnmapViewOfFile.argtypes = (C.c_void_p,)
    kernel32.UnmapViewOfFile.restype = C.c_int

    kernel32.CloseHandle.argtypes = (C.c_void_p,)
    kernel32.CloseHandle.restype = C.c_int

    kernel32.CreateToolhelp32Snapshot.argtypes = (C.c_uint32, C.c_uint32)
    kernel32.CreateToolhelp32Snapshot.restype = C.c_void_p

    kernel32.Process32First.argtypes = (C.c_void_p, C.POINTER(_PROCESSENTRY32))
    kernel32.Process32First.restype = C.c_int

    kernel32.Process32Next.argtypes = (C.c_void_p, C.POINTER(_PROCESSENTRY32))
    kernel32.Process32Next.restype = C.c_int

    kernel32._ets2_winapi_configured = True


class SharedMemoryReader:
    def __init__(self, name: str = MMF_NAME, size: int = MMF_SIZE):
        self.name = name
        self.size = size
        self._handle = None
        self._is_windows = sys.platform == "win32"
        if self._is_windows:
            self._kernel32 = C.windll.kernel32
            _configure_kernel32(self._kernel32)

    def _open(self):
        if not self._is_windows:
            return None
        handle = self._kernel32.OpenFileMappingW(
            FILE_MAP_READ, False, self.name
        )
        if not handle:
            return None
        return handle

    def read(self) -> bytes | None:
        """Zwraca surowe bajty pamieci albo None, gdy obiekt nie istnieje
        (gra nie dziala lub plugin nie jest zaladowany)."""
        if not self._is_windows:
            return None
        handle = self._open()
        if not handle:
            return None
        try:
            addr = self._kernel32.MapViewOfFile(
                handle, FILE_MAP_READ, 0, 0, self.size
            )
            if not addr:
                return None
            try:
                buf = C.string_at(addr, self.size)
                return buf
            finally:
                self._kernel32.UnmapViewOfFile(addr)
        finally:
            self._kernel32.CloseHandle(handle)


def is_game_process_running(names=GAME_PROCESS_NAMES) -> bool:
    """Wykrywa, czy proces gry dziala (niezaleznie od tego, czy plugin
    telemetrii jest zaladowany) przez Toolhelp32 (WinAPI, stdlib ctypes)."""
    if sys.platform != "win32":
        return False
    TH32CS_SNAPPROCESS = 0x00000002

    kernel32 = C.windll.kernel32
    _configure_kernel32(kernel32)
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == INVALID_HANDLE_VALUE:
        return False
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = C.sizeof(_PROCESSENTRY32)
        found = False
        wanted = {n.lower() for n in names}
        if kernel32.Process32First(snapshot, C.byref(entry)):
            while True:
                exe = entry.szExeFile.decode("mbcs", errors="ignore").lower()
                if exe in wanted:
                    found = True
                    break
                if not kernel32.Process32Next(snapshot, C.byref(entry)):
                    break
        return found
    finally:
        kernel32.CloseHandle(snapshot)


# ---------------------------------------------------------------------------
# 4) Budowa pakietu zgodnie z kontraktem + deduplikacja zdarzen
#    (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def make_event_id(delivery_time: int, distance_km: float, earned_xp: int) -> str:
    """event_id deterministyczny z danych zdarzenia (NIE losowy) - revenue
    CELOWO nie wchodzi do tego hasha (patrz client/client.py)."""
    payload = f"{delivery_time}|{round(distance_km, 3)}|{earned_xp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class EventTracker:
    """Wykrywa krawedz (zmiane) flagi special_b.jobDelivered i generuje
    zdarzenie job_delivered. (BEZ ZMIAN wzgledem v0.1.3)"""

    def __init__(self):
        self._last_flag: bool | None = None
        self._sent_ids: set[str] = set()

    def check(self, parsed: dict) -> dict | None:
        flag = parsed["job_delivered_flag"]
        if self._last_flag is None:
            self._last_flag = flag
            return None
        if flag == self._last_flag:
            return None
        self._last_flag = flag
        event_id = make_event_id(
            parsed["job_delivered_delivery_time"],
            parsed["job_delivered_distance_km"],
            parsed["job_delivered_earned_xp"],
        )
        if event_id in self._sent_ids:
            return None
        self._sent_ids.add(event_id)

        revenue_raw = parsed["job_delivered_revenue"]
        if revenue_raw < 0:
            revenue = 0
        else:
            revenue = revenue_raw

        return {
            "type": "job_delivered",
            "event_id": event_id,
            "distance_km": round(parsed["job_delivered_distance_km"], 1),
            "earned_xp": parsed["job_delivered_earned_xp"],
            "revenue": revenue,
        }


def build_packet(connected: bool, running: bool, parsed: dict | None,
                  events: list[dict]) -> dict:
    packet = {
        "v": 2,
        "client": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        "sent_at": iso_now(),
        "game": {
            "running": running,
            "connected": connected,
            "paused": bool(parsed["paused"]) if (connected and parsed) else False,
        },
    }
    if connected and parsed:
        packet["truck"] = {
            "speed_kmh": round(parsed["speed_mps"] * 3.6, 1),
            "rpm": round(parsed["engine_rpm"], 1),
            "gear": parsed["gear"],
            "fuel_l": round(parsed["fuel_l"], 1),
            "fuel_capacity_l": round(parsed["fuel_capacity_l"], 1),
            "odometer_km": round(parsed["odometer_km"], 1),
        }
        position = build_position(parsed)
        if position is not None:
            packet["truck"]["position"] = position
    if events:
        packet["events"] = events[:MAX_EVENTS_PER_PACKET]
    return packet


# ---------------------------------------------------------------------------
# 5) Wysylka HTTP (stdlib urllib) z buforem 60s, backoff na 429, stop na 401
#    + opcjonalne przypinanie certyfikatu SHA-256 (tls_sha256_pin).
#    (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

class ApiError(Exception):
    pass


class FatalAuthError(Exception):
    """401 - klient ma sie zatrzymac."""


class CertPinMismatchError(OSError):
    """Certyfikat serwera nie zgadza sie z tls_sha256_pin z config.json."""


def validate_server_url(url: str) -> None:
    """Wymusza https:// (http:// zabronione) i zabrania fragmentu/zapytania
    w server_url."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            "server_url musi zaczynac sie od https:// (http:// jest "
            f"niedozwolone) - dostalem: {parsed.scheme or '(brak schematu)'}://"
        )
    if not parsed.netloc:
        raise ValueError("server_url nie ma prawidlowego adresu hosta.")
    if parsed.fragment:
        raise ValueError("server_url nie moze zawierac fragmentu (#...).")
    if parsed.query:
        raise ValueError("server_url nie moze zawierac zapytania (?...).")


def _parse_pin(pin_hex: str) -> bytes:
    """Zamienia tls_sha256_pin (hex) na 32 bajty."""
    cleaned = pin_hex.strip().lower().replace(":", "")
    if len(cleaned) != 64 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError(
            "tls_sha256_pin musi byc 64-znakowym ciagiem hex (SHA-256 "
            "certyfikatu serwera w formie hex, bez dwukropkow)."
        )
    return bytes.fromhex(cleaned)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Polaczenie HTTPS, ktore NIE weryfikuje łańcucha CA, ale po
    zakonczeniu negocjacji TLS liczy SHA-256 (DER) certyfikatu serwera i
    porownuje go stalo-czasowo (hmac.compare_digest) z przypisanym pinem."""

    pin_sha256: bytes = b""

    def connect(self):
        raw_sock = socket.create_connection(
            (self.host, self.port), self.timeout
        )
        if getattr(self, "_tunnel_host", None):
            self.sock = raw_sock
            self._tunnel()
            raw_sock = self.sock
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False  # musi byc przed verify_mode=CERT_NONE
        context.verify_mode = ssl.CERT_NONE  # pin zastepuje weryfikacje CA
        tls_sock = context.wrap_socket(raw_sock, server_hostname=self.host)
        try:
            der_cert = tls_sock.getpeercert(binary_form=True)
            if not der_cert:
                raise CertPinMismatchError(
                    "Serwer nie zwrocil certyfikatu podczas negocjacji TLS."
                )
            actual = hashlib.sha256(der_cert).digest()
            if not hmac.compare_digest(actual, self.pin_sha256):
                raise CertPinMismatchError(
                    "certyfikat serwera nie zgadza sie z tls_sha256_pin, "
                    "sprawdz konfiguracje lub zglos problem"
                )
        except CertPinMismatchError:
            tls_sock.close()
            raise
        self.sock = tls_sock


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pin_sha256: bytes):
        super().__init__()
        self._pin_sha256 = pin_sha256

    def https_open(self, req):
        def _conn_factory(host, **kwargs):
            conn = _PinnedHTTPSConnection(host, **kwargs)
            conn.pin_sha256 = self._pin_sha256
            return conn

        return self.do_open(_conn_factory, req)


class TelemetrySender:
    def __init__(self, server_url: str, token: str, tls_sha256_pin: str | None = None):
        validate_server_url(server_url)
        self.endpoint = server_url.rstrip("/") + ENDPOINT_PATH
        self._token = token  # NIGDY nie logowac / wypisywac
        self._backoff = 1.0
        if tls_sha256_pin:
            pin_bytes = _parse_pin(tls_sha256_pin)
            self._opener = urllib.request.build_opener(
                _PinnedHTTPSHandler(pin_bytes)
            )
        else:
            self._opener = None  # tryb domyslny: pelna weryfikacja CA

    def send(self, packet: dict) -> int:
        body = json.dumps(packet).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            opener_open = (
                self._opener.open if self._opener is not None else urllib.request.urlopen
            )
            with opener_open(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._backoff = 1.0
                return resp.status
        except CertPinMismatchError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise FatalAuthError(
                    "Serwer odrzucil token (401). Sprawdz token w config.json "
                    "w panelu konta na szosownia.com."
                )
            raise ApiError(f"HTTP {e.code}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, CertPinMismatchError):
                raise e.reason from None
            raise ApiError(f"network: {e}")
        except (socket.timeout, OSError) as e:
            raise ApiError(f"network: {e}")

    def backoff_sleep(self):
        time.sleep(min(self._backoff, BACKOFF_MAX_S))
        self._backoff = min(self._backoff * 2, BACKOFF_MAX_S)


# ---------------------------------------------------------------------------
# 6) Linia statusu (diagnostyka) - identyczna trescia co v0.1.3, uzywana
#    teraz jako tekst w polu statusu okna GUI zamiast linii konsoli.
#    (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

def status_line(running: bool, connected: bool) -> str:
    """Zwraca jedna linie opisujaca stan (gra / pamiec SCS). Nigdy nie
    zawiera tokena ani innych danych z konfiguracji."""
    if not running:
        return "[status] gra nie jest uruchomiona"
    if not connected:
        return (
            "[status] gra działa, pamięć SCS: niedostępna "
            "(sprawdź plugin w bin\\win_x64\\plugins)"
        )
    return "[status] gra działa, pamięć SCS: dostępna"


# ---------------------------------------------------------------------------
# 7) Odporna na bledy pamieci petla - safe_read_memory() i
#    safe_parse_telemetry() (BEZ ZMIAN wzgledem v0.1.3)
# ---------------------------------------------------------------------------

def safe_read_memory(reader) -> tuple[bytes | None, str | None]:
    """Wrapper wokol reader.read() chwytajacy OSError / ctypes.ArgumentError
    / ValueError. Zwraca (raw_bytes_albo_None, opis_bledu_albo_None)."""
    try:
        return reader.read(), None
    except (OSError, C.ArgumentError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


def safe_parse_telemetry(raw: bytes) -> tuple[dict | None, str | None]:
    """Jak wyzej, dla parse_telemetry()."""
    try:
        return parse_telemetry(raw), None
    except (OSError, C.ArgumentError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


def mem_error_status_line(err_msg: str) -> str:
    """Jedna linia diagnostyczna dla bledu odczytu/parsowania pamieci SCS."""
    return f"[status] błąd odczytu pamięci SCS: {err_msg}, ponawiam"
