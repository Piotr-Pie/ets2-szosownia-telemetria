# ETS2 Szosownia — instalator telemetrii v0.2.2 (jeden plik .exe)

Ten program czyta dane z gry Euro Truck Simulator 2 (prędkość, obroty,
bieg, paliwo, przebieg) i wysyła je na żywo do Twojego konta na
szosownia.com. Działa WYŁĄCZNIE na Twoim komputerze z Windows, w tle,
kiedy grasz. Od v0.2.2 program ma ikonę w zasobniku systemowym, może
startować razem z Windows i zrobić sobie skrót na pulpicie — patrz
sekcja „Nowości w v0.2.2” niżej.

Token dostępu nigdy nie jest wypisywany na ekranie, w logu, w tytule
okna ani nigdzie zapisywany poza plikiem konfiguracyjnym opisanym
poniżej.

## Nowości w v0.2.2

- **Ikona w zasobniku systemowym** (przy zegarze) — litera „S” w kolorach
  strony (bez logotypów SCS/Steam). Klik na ikonę pokazuje okno. Menu
  (prawy klik): „Pokaż okno”, „Wstrzymaj wysyłkę” / „Wznów wysyłkę”,
  „Zakończ”. Tooltip ikony pokazuje ten sam tekst co pole statusu.
- **Zamknięcie okna (X)** teraz CHOWA program do zasobnika (nie zamyka
  go) — wysyłka działa dalej w tle. Żeby naprawdę zamknąć program, użyj
  „Zakończ” z menu zasobnika.
- **Checkbox „Uruchamiaj razem z Windows”** (domyślnie WYŁĄCZONY). Po
  włączeniu program startuje razem z Windows, od razu zminimalizowany do
  zasobnika, i — jeśli token był już zapisany wcześniej — zaczyna wysyłać
  dane automatycznie, bez klikania niczego.
- **Przycisk „Utwórz skrót na pulpicie”** — tworzy skrót do programu na
  Twoim pulpicie.
- **Jedna instancja programu** — drugie kliknięcie w .exe (albo w jego
  skrót) nie otwiera drugiego okna, tylko przywołuje już uruchomione.

## Instalacja — krok po kroku (bez cmd, bez Pythona, bez edycji plików)

1. Pobierz `ETS2-Szosownia-Telemetria-v0.2.2.exe` ze strony
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
8. (Opcjonalnie) Zaznacz „Uruchamiaj razem z Windows”, jeśli chcesz, żeby
   program startował sam przy włączeniu komputera — i/albo kliknij
   „Utwórz skrót na pulpicie”.

Żeby zatrzymać wysyłanie danych, kliknij „Zatrzymaj” (w oknie) albo
„Wstrzymaj wysyłkę” (w menu zasobnika). Zamknięcie okna (X) NIE zatrzymuje
wysyłki — program dalej działa w zasobniku; użyj „Zakończ” z menu
zasobnika, żeby naprawdę zamknąć program.

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
app.py                  - okno tkinter (GUI), pętla wysyłkowa w wątku,
                           zasobnik (pystray), autostart, skrót (v0.2.2)
core/ets2_core.py       - rdzeń przeniesiony z client/client.py v0.1.4
                           (parser pamięci, pozycja/kierunek truck.position,
                           wysyłka, dedup, TLS pin, poprawki kernel32)
                           BEZ ZMIAN MERYTORYCZNYCH
core/game_finder.py      - wyszukiwanie gry (rejestr Steam + libraryfolders.vdf),
                           port 1:1 logiki z client/install.ps1
core/config_store.py      - zapis/odczyt %APPDATA%\ETS2Szosownia\config.json
core/plugin_installer.py  - kopiowanie DLL + weryfikacja SHA-256
core/autostart.py         - wpis HKCU Run (autostart z Windows), v0.2.2
core/shortcut.py           - skrót .lnk na pulpicie przez PowerShell, v0.2.2
core/single_instance.py    - named mutex (jedna instancja programu), v0.2.2
core/tray_icon.py          - obraz ikony zasobnika (Pillow), v0.2.2
core/window_controller.py  - logika "X = chowaj do zasobnika", v0.2.2
assets/scs-telemetry.dll  - plugin SCS SDK (wbudowywany w .exe)
build.spec                - specyfikacja PyInstaller (--onefile --windowed)
requirements.txt           - zaleznosci GUI (pystray, Pillow), v0.2.2
tests/                    - testy (patrz niżej, uruchamiane na Linuksie)
.github/workflows/build.yml - budowa automatyczna na windows-latest (GitHub Actions)
```

Budowa lokalna (wymaga Windows, do testów deweloperskich):

```
pip install pyinstaller -r requirements.txt
pyinstaller build.spec
# wynik: dist\ETS2-Szosownia-Telemetria-v0.2.2.exe
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
python3 tests/test_autostart.py
python3 tests/test_shortcut.py
python3 tests/test_single_instance.py
python3 tests/test_tray_icon.py
python3 tests/test_window_controller.py
```
