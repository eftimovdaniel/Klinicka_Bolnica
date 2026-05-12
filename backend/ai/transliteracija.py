"""
Конверзија: македонска латиница → кирилица.

Зашто:
- Корисниците често пишуваат на латиница ("zakazi", "Aleksandar")
- Сите наши клучни зборови и Gemini промптови се на кирилица
- Подобро да конвертираме на старт отколку да дупликаме листи

Особености:
- Зачувува зборови што се веќе на кирилица
- Третира мешан текст ("Сакам zakazi termin")
- Третира посебни диграми: dz, dj, lj, nj, zh, sh, ch, gj, kj
"""

import re

# Прв чекор: посебни знаци (са „капки") → нивен ASCII еквивалент
# („zakažeš" → „zakazhesh" пред главната конверзија)
SPECIJALNI = {
    "š": "sh", "Š": "Sh",
    "ž": "zh", "Ž": "Zh",
    "č": "ch", "Č": "Ch",
    "ć": "kj", "Ć": "Kj",
    "đ": "dj", "Đ": "Dj",
    "ǵ": "gj", "Ǵ": "Gj",
    "ḱ": "kj", "Ḱ": "Kj",
    "ñ": "nj", "Ñ": "Nj",
    "ĺ": "lj", "Ĺ": "Lj",
    "ʒ": "dz",
}


# Редот е важен - подолгите диграми прво
PRESLIKUVANJA = [
    ("dz", "ѕ"), ("Dz", "Ѕ"), ("DZ", "Ѕ"),
    ("dj", "ѓ"), ("Dj", "Ѓ"), ("DJ", "Ѓ"),
    ("gj", "ѓ"), ("Gj", "Ѓ"), ("GJ", "Ѓ"),
    ("kj", "ќ"), ("Kj", "Ќ"), ("KJ", "Ќ"),
    ("lj", "љ"), ("Lj", "Љ"), ("LJ", "Љ"),
    ("nj", "њ"), ("Nj", "Њ"), ("NJ", "Њ"),
    ("zh", "ж"), ("Zh", "Ж"), ("ZH", "Ж"),
    ("sh", "ш"), ("Sh", "Ш"), ("SH", "Ш"),
    ("ch", "ч"), ("Ch", "Ч"), ("CH", "Ч"),
    ("ts", "ц"), ("Ts", "Ц"), ("TS", "Ц"),
    # Поединечни букви
    ("a", "а"), ("A", "А"),
    ("b", "б"), ("B", "Б"),
    ("v", "в"), ("V", "В"),
    ("g", "г"), ("G", "Г"),
    ("d", "д"), ("D", "Д"),
    ("e", "е"), ("E", "Е"),
    ("z", "з"), ("Z", "З"),
    ("i", "и"), ("I", "И"),
    ("j", "ј"), ("J", "Ј"),
    ("k", "к"), ("K", "К"),
    ("l", "л"), ("L", "Л"),
    ("m", "м"), ("M", "М"),
    ("n", "н"), ("N", "Н"),
    ("o", "о"), ("O", "О"),
    ("p", "п"), ("P", "П"),
    ("r", "р"), ("R", "Р"),
    ("s", "с"), ("S", "С"),
    ("t", "т"), ("T", "Т"),
    ("u", "у"), ("U", "У"),
    ("f", "ф"), ("F", "Ф"),
    ("h", "х"), ("H", "Х"),
    ("c", "ц"), ("C", "Ц"),
    # x, y, w, q - ретко во македонски
    ("x", "кс"), ("X", "Кс"),
    ("y", "ј"), ("Y", "Ј"),
    ("w", "в"), ("W", "В"),
    ("q", "к"), ("Q", "К"),
]

# Зборови што не треба да се конвертираат (англиски технички термини, мерки)
# Ако цел збор е во оваа листа, не го допирај.
ZADRZUVAJ = {
    "ok", "OK", "Ok",
    "email", "Email", "EMAIL",
    "mail", "Mail",
    "wifi", "Wifi", "WiFi", "WIFI",
    "id", "ID",
    "ER", "er",
    "URL", "url",
    "PDF", "pdf",
    "https", "http",
}


def _ima_kirilica(zbor: str) -> bool:
    """Проверка дали зборот веќе содржи кирилица."""
    return any('\u0400' <= ch <= '\u04FF' for ch in zbor)


def _konvertiraj_zbor(zbor: str) -> str:
    """Конвертира еден збор од латиница на кирилица."""
    if not zbor:
        return zbor
    if zbor in ZADRZUVAJ:
        return zbor
    if _ima_kirilica(zbor):
        # Веќе на кирилица - не допирај (или мешан, мала шанса)
        return zbor

    rezultat = zbor
    # 1. Прво: специјални знаци (š → sh, ž → zh, итн.)
    for sp, ascii_eq in SPECIJALNI.items():
        rezultat = rezultat.replace(sp, ascii_eq)
    # 2. Потоа: латиница → кирилица
    for lat, kir in PRESLIKUVANJA:
        rezultat = rezultat.replace(lat, kir)
    return rezultat


def transliterijaj(tekst: str) -> str:
    """
    Конвертирај латински зборови во кирилица. Зачувај интерпункција и кирилица.

    Примери:
        "Zakazi mi pregled kaj Serafimov" → "Закази ми преглед кај Серафимов"
        "Сакам преглед kaj Petrov utre" → "Сакам преглед кај Петров утре"
        "OK, zakazi za 12:30" → "OK, закази за 12:30"

    Број, интерпункција, белина се зачувуваат.
    """
    if not tekst:
        return tekst

    # Разбиј по не-алфанумерички знаци, конвертирај секој збор поединечно
    delovi = re.split(r'(\W+)', tekst)
    rezultat = []
    for d in delovi:
        # Ако делот содржи букви - конвертирај, инаку остави го
        if re.search(r'[A-Za-z]', d):
            rezultat.append(_konvertiraj_zbor(d))
        else:
            rezultat.append(d)
    return "".join(rezultat)


def normaliziraj_prashanje(tekst: str) -> str:
    """
    Главна функција за нормализација на корисничко прашање:
    1. Тргни вишок белина
    2. Конвертирај латиница → кирилица
    3. Долна буква (lowercase) за keyword matching

    Враќа: (originalniot tekst, normaliziran tekst)
    """
    if not tekst:
        return ""
    t = tekst.strip()
    t = transliterijaj(t)
    return t
