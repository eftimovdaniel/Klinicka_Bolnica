"""
Заеднички функции за сите routers
"""


def transliterate_mk_to_lat(text):
    """Конвертира македонски текст од кирилица во латиница"""
    if not text:
        return ""

    # mora da go imam bidejki nekoj iminja ne moze da se poznaat poradi toa so mora da se najavaeme na laticica

    translit_map = {
        "Ѓ": "gj",
        "ѓ": "gj",
        "Ѕ": "dz",
        "ѕ": "dz",
        "Љ": "lj",
        "љ": "lj",
        "Њ": "nj",
        "њ": "nj",
        "Ќ": "kj",
        "ќ": "kj",
        "Џ": "dzh",
        "џ": "dzh",
        "Ч": "ch",
        "ч": "ch",
        "Ш": "sh",
        "ш": "sh",
        "Ж": "zh",
        "ж": "zh",
        "А": "a",
        "а": "a",
        "Б": "b",
        "б": "b",
        "В": "v",
        "в": "v",
        "Г": "g",
        "г": "g",
        "Д": "d",
        "д": "d",
        "Е": "e",
        "е": "e",
        "З": "z",
        "з": "z",
        "И": "i",
        "и": "i",
        "Ј": "j",
        "ј": "j",
        "К": "k",
        "к": "k",
        "Л": "l",
        "л": "l",
        "М": "m",
        "м": "m",
        "Н": "n",
        "н": "n",
        "О": "o",
        "о": "o",
        "П": "p",
        "п": "p",
        "Р": "r",
        "р": "r",
        "С": "s",
        "с": "s",
        "Т": "t",
        "т": "t",
        "У": "u",
        "у": "u",
        "Ф": "f",
        "ф": "f",
        "Х": "h",
        "х": "h",
        "Ц": "c",
        "ц": "c",
    }

    result = ""
    for char in text:
        repl = translit_map.get(char)
        result += repl if repl is not None else char.lower()
    return result
