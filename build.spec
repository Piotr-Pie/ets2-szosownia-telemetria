# -*- mode: python ; coding: utf-8 -*-
# ETS2 Szosownia - PyInstaller spec, v0.2.6
# ==========================================
# Budowany na runs-on: windows-latest (patrz .github/workflows/build.yml,
# PUSH automatyczny z konta Piotr-Pie - patrz raport o zakresie tokena).
#
# --onefile --windowed (bez konsoli), DLL pluginu wbudowany jako dane
# (--add-data), nazwa wynikowa:
#   ETS2-Szosownia-Telemetria-v0.2.6.exe
#
# v0.2.2: zasobnik systemowy (pystray + Pillow) - workflow instaluje
# pystray+Pillow PRZED `pyinstaller build.spec` (zweryfikowane w sesji
# v0.2.3 - .github/workflows/build.yml NIE jest tu zmieniany).
#
# v0.2.3: wariant B autostartu - start z --tray TYLKO chowa do zasobnika,
# wysylka NIE startuje automatycznie (patrz app.py). Bez zmian w
# build.spec poza nazwa wynikowego .exe.
#
# v0.2.4: wysylka aktualnego zlecenia (job, kontrakt v3) - logika w
# core/ets2_core.py, BEZ ZMIAN w build.spec poza nazwa wynikowego .exe
# (zasobnik/autostart/skrot/pozycja/wariant B autostartu - bez zmian).
#
# v0.2.5: statystyki dostawy (fuel_avg_consumption, job_stats, kontrakt
# v4) - logika w core/ets2_core.py + nowy modul core/job_stats.py
# (dodany do hiddenimports nizej, zebyPyInstaller go nie zgubil), BEZ
# ZMIAN w pozostalej czesci build.spec poza nazwa wynikowego .exe.
#
# v0.2.6: pelny gating wysylki (manual pause / auto pause / baseline,
# kontrakt v5) - logika w NOWYM module core/telemetry_worker.py
# (dodany do hiddenimports nizej), BEZ ZMIAN w pozostalej czesci
# build.spec poza nazwa wynikowego .exe.
#
# Budowa lokalna (Windows, do testow deweloperskich):
#   pip install pyinstaller -r requirements.txt
#   pyinstaller build.spec
#
# Ikona: brak (opcjonalna, NIE uzywamy logotypow SCS/Steam - zgodnie ze
# zleceniem). Dodanie wlasnej ikony: ustaw icon='assets/app.ico' nizej.

import sys

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/scs-telemetry.dll', 'assets'),
    ],
    hiddenimports=[
        'core',
        'core.ets2_core',
        'core.job_stats',
        'core.telemetry_worker',
        'core.game_finder',
        'core.config_store',
        'core.plugin_installer',
        'core.autostart',
        'core.shortcut',
        'core.single_instance',
        'core.tray_icon',
        'core.window_controller',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.ttk',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ETS2-Szosownia-Telemetria-v0.2.6',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # --windowed: bez okna konsoli
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,            # brak logotypow SCS/Steam - zgodnie ze zleceniem
)
