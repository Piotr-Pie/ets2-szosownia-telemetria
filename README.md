# ETS2 Szosownia — instalator telemetrii v0.2.1 (jeden plik .exe)

Ten program czyta dane z gry Euro Truck Simulator 2 (prędkość, obroty,
bieg, paliwo, przebieg) i wysyła je na żywo do Twojego konta na
szosownia.com. Działa WYŁĄCZNIE na Twoim komputerze z Windows, w tle,
kiedy grasz.

Token dostępu nigdy nie jest wypisywany na ekranie, w logu, w tytule
okna ani nigdzie zapisywany poza plikiem konfiguracyjnym opisanym
poniżej.

## Instalacja — krok po kroku (bez cmd, bez Pythona, bez edycji plików)

1. Pobierz `ETS2-Szosownia-Telemetria-v0.2.1.exe` ze strony
   szosownia.com/pobierz.
2. Kliknij dwukrotnie plik — otworzy się małe okno programu.
3. Na szosownia.com zaloguj się przez Steam, wejdź w „Konto” i wygeneruj
   token klienta (pokazany **tylko raz**).
4. Wklej token do pola w oknie programu.
5. Program automatycznie szuka Euro Truck Simulator 2 (rejestr Steam,
   wszystkie biblioteki Steam, domyślna ścieżka). Jeśli napis pod polem
   tokena mówi, że gra została znaleziona — nic więcej nie trzeba robić.
   Jeśli nie — kliknij „Wybierz folder gry…” i wskaż folder główny
   Euro Truck Simulator 2 (Steam → Biblioteka → prawy klik na grze →
   Zarządzaj → Przeglądaj pliki lokalne).
6. Kliknij „Zapisz i uruchom”. Program zainstaluje plugin telemetrii do
   gry i zacznie wysyłać dane.
7. Uruchom (albo przełącz się do) grę Euro Truck Simulator 2 i wjedź do
   kabiny — po chwili dane powinny pojawić się na Twoim profilu na
   szosownia.com.

Żeby zatrzymać wysyłanie danych, kliknij „Zatrzymaj” albo zamknij okno
programu.

## Co robi program, krok po kroku (dla zainteresowanych)

- Zapisuje token w `%APPDATA%\ETS2Szosownia\config.json` (tworzy ten
  katalog przy pierwszym zapisie, jeśli nie istnieje).
- Kopiuje wbudowany plugin `scs-telemetry.dll` do
  `...\Euro Truck Simulator 2\bin\win_x64\plugins\` i sprawdza SHA-256
  skopiowanego pliku (jeśli tam już jest inna/starsza wersja pliku —
  podmienia ją).
- Czyta dane z pamięci współdzielonej gry (`Local\SCSTelemetry`, 32 KB)
  i wysyła je do `https://szosownia.com` ok. 2 razy w sekundę, gdy gra
  działa, albo raz na 5 sekund („jestem offline”), gdy gra nie jest
  uruchomiona.
- Buforuje do 60 sekund danych, gdy nie ma internetu, i wysyła je po
  powrocie sieci.
- Zatrzymuje się i pokazuje komunikat, jeśli serwer odrzuci token (401) —
  wtedy trzeba wygenerować nowy token na szosownia.com/konto.

## Jakie dane wysyła

Zgodnie z kontraktem `telemetry-contract-v2` (wstecznie zgodnym z v1,
ustalonym z serwerem strony) — te same pola co w ZIP (v0.1.4):

- Status gry: czy gra działa, czy jest dostępna telemetria, czy gra jest
  w pauzie.
- Dane pojazdu: prędkość (km/h), obroty silnika (RPM), bieg, poziom
  paliwa (litry), pojemność zbiornika (litry), przebieg (km).
- **Nowość od v0.2.1: pozycja na mapie** — współrzędne X/Z świata gry i
  kierunek jazdy (0–360°), widoczna wyłącznie na Twoim koncie. Gdy
  odczyt pozycji z gry się nie powiedzie, pole jest po prostu pominięte
  (nigdy zera zamiast prawdziwej pozycji).
- Zdarzenie „dostawa zrealizowana”: dystans dostawy (km), zdobyte XP i
  zarobek z zadania — wysyłane tylko raz na dostawę (deduplikacja po
  `event_id`).

## Rozwiązywanie problemów

**Program pokazuje „Token odrzucony — wygeneruj nowy na szosownia.com/konto”**
Wygeneruj nowy token w panelu „Konto” na szosownia.com, wklej go do pola
w programie i kliknij „Zapisz i uruchom” jeszcze raz.

**Program nie znajduje gry automatycznie**
Kliknij „Wybierz folder gry…” i wskaż główny folder Euro Truck Simulator 2
(Steam → Biblioteka → prawy klik na grze → Zarządzaj → Przeglądaj pliki
lokalne — skopiuj ścieżkę z okna Eksploratora).

**Windows SmartScreen / antywirus blokuje program**
Program nie jest (jeszcze) podpisany cyfrowo, więc Windows może pokazać
ostrzeżenie „Nieznany wydawca” przy pierwszym uruchomieniu — kliknij
„Więcej informacji” → „Uruchom i tak”. To samo może dotyczyć niektórych
antywirusów (plugin modyfikuje pamięć procesu gry, co jest typowym
powodem false-positive dla narzędzi telemetrii gier). Plik można
zweryfikować przez sumę SHA-256 podaną na stronie pobierania.

**Chcę odinstalować**
Usuń plik `...\Euro Truck Simulator 2\bin\win_x64\plugins\scs-telemetry.dll`,
usuń folder `%APPDATA%\ETS2Szosownia` i usuń sam plik .exe. To wszystko —
program nie zmienia niczego innego na komputerze.

## Pochodzenie pluginu (dla zainteresowanych / do audytu)

- Repozytorium: https://github.com/truckermudgeon/scs-sdk-plugin (MIT,
  fork RenCloud/scs-sdk-plugin)
- Commit źródłowy użyty do wyliczenia układu pamięci:
  `c8910d6e9a5ca0c2fa018942054263292cab19a4`
- SHA-256 pliku DLL: `d8d273d21759a53c09320d5375d0b7cc871aab1d69bbebefc86a14a5e53ca454`
- Plugin czyta dane gry do obiektu pamięci współdzielonej Windows
  `Local\SCSTelemetry` (32 KB). Program tylko to CZYTA — nic nie
  wstrzykuje do gry i nie modyfikuje jej pliku wykonywalnego.

## Dla developerów — struktura repo i budowa

```
app.py                  - okno tkinter (GUI), pętla wysyłkowa w wątku
core/ets2_core.py       - rdzeń przeniesiony z client/client.py v0.1.4
                           (parser pamięci, pozycja/kierunek truck.position,
                           wysyłka, dedup, TLS pin, poprawki kernel32)
                           BEZ ZMIAN MERYTORYCZNYCH
core/game_finder.py      - wyszukiwanie gry (rejestr Steam + libraryfolders.vdf),
                           port 1:1 logiki z client/install.ps1
core/config_store.py      - zapis/odczyt %APPDATA%\ETS2Szosownia\config.json
core/plugin_installer.py  - kopiowanie DLL + weryfikacja SHA-256
assets/scs-telemetry.dll  - plugin SCS SDK (wbudowywany w .exe)
build.spec                - specyfikacja PyInstaller (--onefile --windowed)
tests/                    - testy (patrz niżej, uruchamiane na Linuksie)
.github/workflows/build.yml - budowa automatyczna na windows-latest (GitHub Actions)
```

Budowa lokalna (wymaga Windows, do testów deweloperskich):

```
pip install pyinstaller
pyinstaller build.spec
# wynik: dist\ETS2-Szosownia-Telemetria-v0.2.1.exe
```

Testy (Linux, bez GUI/rejestru Windows — patrz zastrzeżenia w każdym
pliku testowym):

```
python3 tests/test_parser.py
python3 tests/test_sender.py
python3 tests/test_tls_pin.py
python3 tests/test_status_line.py
python3 tests/test_kernel32_winapi.py
python3 tests/test_game_finder.py
python3 tests/test_config_store.py
python3 tests/test_plugin_installer.py
python3 tests/test_no_token_leak.py
```
