#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETS2 Szosownia - ikona zasobnika systemowego (v0.2.2)
========================================================

NOWY KOD. Buduje obraz ikony zasobnika (Pillow, bez zadnych zewnetrznych
plikow graficznych/logotypow) - prosta litera "S" w kolku, kolory ze
systemu wizualnego strony: tlo #0e1522, rysunek #5cbfae. ZADNYCH
logotypow SCS/Steam (zgodnie ze zleceniem).

Rzeczywisty obiekt zasobnika (pystray.Icon) jest tworzony w app.py (tam
tez jest menu "Pokaz okno"/"Wstrzymaj wysylke / Wznow"/"Zakoncz" - to
wymaga tkinter/pystray zyjacych w tej samej aplikacji, wiec nie jest
tutaj). Ten modul zawiera WYLACZNIE czysta funkcje budujaca obraz
(testowalna bez zadnego srodowiska graficznego/zasobnika - patrz
tests/test_tray_icon.py), zeby import pystray+Pillow dalo sie zweryfikowac
osobno od reszty logiki zasobnika.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

COLOR_BG = "#0e1522"
COLOR_FG = "#5cbfae"


def build_icon_image(size: int = 64) -> Image.Image:
    """Zwraca kwadratowy obraz RGBA size x size: kolko w kolorze COLOR_FG
    na tle COLOR_BG, z litera 'S' wysrodkowana w kolku. Uzywa WYLACZNIE
    Pillow (brak zewnetrznych plikow/fontow - ImageFont.load_default())."""
    img = Image.new("RGBA", (size, size), COLOR_BG)
    draw = ImageDraw.Draw(img)

    margin = max(2, size // 16)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=COLOR_FG,
        width=max(2, size // 12),
    )

    text = "S"
    try:
        font = ImageFont.load_default(size=max(10, size // 2))
    except TypeError:
        # starsze Pillow bez argumentu size w load_default()
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) / 2 - bbox[0]
    y = (size - text_h) / 2 - bbox[1]
    draw.text((x, y), text, fill=COLOR_FG, font=font)

    return img
