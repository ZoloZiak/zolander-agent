#!/usr/bin/env python3
"""zone.py — zdielany whitelist ulic v cielovej zone (Rondo Daszynskiego / Proximo /
Aldi / Fabryka Norblina / Lidl). Pouzivaju ho vsetky source_*.py moduly.

DOVOD: geokoder (Nominatim) je NESPOLAHLIVY pre PL cisla domov -> robil false-positives
(Karolkowa 78 "218m" realne 965m) AJ false-negatives (realne blizke ulice hodene daleko,
watcher ich zamlcal). Nazov ulice v texte je 100x spolahlivejsi signal nez geokod suradnica.
Preto: PRIMARNY filter = whitelist ulic (substring). Geokod ostava len ako DOPLNKOVA
vzdialenost do zobrazenia, NIE ako gate.

Vzdialenosti su rucne overene z MAP (nie z hlavy!) 2026-08. Referencne body OVERENE cez
Nominatim/Overpass: Proximo I+II = 52.2306,20.9813 (Prosta 68 / Przyokopowa 26);
Aldi = Karolkowa 30 (52.23213,20.97810); Lidl = Wolska 19/25 (52.23497,20.97626).
POZOR: NIKDY nezadavaj ref body odhadom — Proximo NIE je Przyokopowa 33 (to je Wola Center),
Aldi NIE je pri Towarowej. APPROX_M nizsie = orientacny stred ulice od Proximo.
"""

# substring ulice (lowercase, bez diakritiky-variantov oboje) -> orientacna vzdialenost [m]
# od PRACE (Proximo). Len ulice realne v pesej dostupnosti Proximo/Aldi/Ronda.
ZONE_STREETS = {
    "hrubieszow": 128,     # NAJBLIZSIE k praci (Proximo), pridane 2026-08
    "grzybowsk": 170,
    "przyokopow": 142,
    "prosta": 250,
    "towarow": 320,
    "gieldow": 240, "giełdow": 240,
    "jaktorowsk": 350,
    "karolkow": 190,       # POZOR: dlha ulica, cislo 78 je az ~965m! over cislo domu
    "siedmiogrodzk": 266,
    "lucka": 400, "łucka": 400,
    "krochmaln": 500,
    "wronia": 443,
    "kolejow": 500,
    "walicow": 480, "waliców": 480,
    "chlodna": 500, "chłodna": 500,
    "panska": 520, "pańsk": 520,
    "wolska": 464,
    "skierniewick": 550,
    "miedziana": 500,
    "srebrna": 520,
    "kasprzaka": 620,
    "ordona": 600,
}

# ulice ktore v texte matchuju ale su ZAVADZAJUCE (mimo zony) — nikdy nie su tu, vylucit
# (napr. cislo domu robi rozdiel; ponechane prazdne, riesi sa cez cislo domu v moduloch)


def zone_hit(*texts):
    """Vrat (matched_substring, approx_m) ak niektory z textov (street, title...) obsahuje
    zonovu ulicu; inak (None, None). Berie prvy najblizsi match."""
    blob = " ".join(t for t in texts if t).lower()
    best = None
    for sub, dist in ZONE_STREETS.items():
        if sub in blob:
            if best is None or dist < best[1]:
                best = (sub, dist)
    return best if best else (None, None)
