"""
Детектор на интент - хибриден пристап:

1. ПРВО: проверка преку клучни зборови (брзо, бесплатно, локално)
2. ФАЛБЕК: ако не најде совпаѓање → праша AI (Groq)

Зашто хибрид?
- 80% од прашањата се на „стандардни" фрази → keyword се справува моментално
- 20% природни варијации ("Dali možeš da mi...") → AI ги препознава

Сите прашања прво се транслитираат латиница → кирилица.

Поддржани интенти:
- "zakazi_termin"     → закажување нов термин (INSERT во база)
- "otkazi_termin"     → откажување постоечки термин (UPDATE статус)
- "prenesi_termin"    → пренесување термин на друг датум/време (UPDATE)
- "postavi_potsetnik" → потсетник за термин (INSERT во Potsetnici)
- "oceni_pregled"     → оцена за завршен преглед (INSERT во Pregled_feedback)
- "trgni_ocena"       → бришење на оцена (DELETE од Pregled_feedback)
- "slobodni_termini"  → преглед на слободни термини
- "info_lekar"        → информации за конкретен лекар
- "preporaka_lekar"   → препорака според симптом
- "rabotno_vreme"     → работно време
- "lokacija"          → локации на оддели
- "kontakti"          → контакти на болницата
- "uslugi"            → список на услуги
- "general"           → одговор од AI за општо прашање

ВАЖНО: Редот на проверки е важен (поспецифичните прво).
"""


# 0a. ТРГНИ / ИЗБРИШИ ОЦЕНА (мора пред "оцени" и пред "откажи")
KLUCNI_TRGNI_OCENA = [
    "тргни ја оцената", "тргни ja оцената", "тргни оцена",
    "избриши ја оцената", "избриши оцена", "избришe оцена",
    "избриши го рејтингот", "тргни рејтинг",
    "отстрани оцена", "отстрани ја оцената",
]

# 0b. ОЦЕНИ ПРЕГЛЕД (пред "откажи")
KLUCNI_OCENI = [
    "оцена", "оценувам", "оценете",
    "оцени го", "оцени ја", "оцени",
    "давам оцена", "сакам да оценам",
    "рејтинг", "коментар за",
    "беше одличен", "беше многу добар",
]

# 0c. ПОСТАВИ ПОТСЕТНИК (пред "откажи" - за случај „потсети ме")
KLUCNI_POTSETNIK = [
    "потсети", "потсетник", "потсетувај",
    "напомени ми", "потсети ме",
    "ремаиндер", "remind",
]

# 0d. ПРЕНЕСИ / ПРЕФРЛИ ТЕРМИН (пред "откажи" и пред "закажи")
KLUCNI_PRENESI = [
    "префрли", "пренеси", "поместе", "помести",
    "промени датум", "промени термин", "промени време",
    "одложи", "одложи термин", "пренасрочи",
    "rescheduling", "reschedule",
]

# 0e. ОТКАЖИ ТЕРМИН (пред "закажи")
KLUCNI_OTKAZI = [
    "откажи", "откажете", "откажување",
    "сторнирај", "сторно", "поништи термин",
    "не сакам термин", "не доаѓам",
    "cancel termin",
]

# 1. ЗАКАЖУВАЊЕ
KLUCNI_ZAKAZI = [
    "закажи", "закажете", "закажување", "закажеш", "закаж",
    "сакам преглед", "сакам термин", "сакам да закажам",
    "би сакал", "би сакала", "би сакал/а",
    "резервирај", "резервација", "резервирам",
    "запиши ме", "запиши го",
    "земи термин", "ми треба термин", "имам потреба од термин",
    "ми треба преглед", "имам потреба од преглед",
    "можеш да закажеш", "можеш ли да закажеш",
    "дали можеш", "дали можете",
]

# 2. ПРЕПОРАКА СПОРЕД СИМПТОМ
KLUCNI_PREPORAKA = [
    "болка", "ме боли", "имам болка",
    "симптом", "симптоми",
    "грозница", "температура",
    "кашлица", "главоболка",
    "кому да", "на кој лекар", "кој лекар да",
    "препорака", "препорачај",
]

# 4. РАБОТНО ВРЕМЕ
KLUCNI_RABOTNO = [
    "работно време", "кога е отворен", "кога е отворено",
    "кога работи болницата", "кога ради болницата",
    "кога е затворен", "работни денови",
]

# 5. ЛОКАЦИЈА
KLUCNI_LOKACIJA = [
    "каде е", "каде се наоѓа", "локација",
    "адреса", "како да дојдам", "како да стигнам",
    "во кој спрат", "кој спрат", "соба",
]

# 6. КОНТАКТИ
KLUCNI_KONTAKTI = [
    "телефон", "број", "контакт",
    "на кој број", "како да јавам", "како да повикам",
    "итна помош", "ургентно",
    "email", "е-пошта",
]

# 7. УСЛУГИ
KLUCNI_USLUGI = [
    "услуги", "услугите", "какви услуги",
    "што нудите", "што имате",
    "специјалности", "оддели",
]

# 8. ИНФО ЗА ЛЕКАР
KLUCNI_INFO_LEKAR = [
    "каков е", "каква е", "кој е",
    "информации за", "инфо за", "повеќе за",
    "опис на лекар",
]

# 9. СЛОБОДНИ ТЕРМИНИ
KLUCNI_SLOBODNI = [
    "слободен", "слободна", "слободни", "слободно",
    "кога е слободен", "кога е слободна",
    "кога ради", "кога работи",
]


from ai.transliteracija import transliterijaj
from ai.ai_intent_detector import detektiraj_intent_so_ai


def _ima_zbor(prashanje: str, kluchni: list[str]) -> bool:
    """Помошна функција - проверка на клучни зборови."""
    return any(zbor in prashanje for zbor in kluchni)


def detektiraj_intent_keyword(prashanje: str) -> str | None:
    """
    Брза проверка преку клучни зборови.
    Враќа: име на интент ИЛИ None ако нема јасно совпаѓање.
    """
    if not prashanje:
        return None

    # Автоматски преводи: латиница → кирилица
    p = transliterijaj(prashanje).lower().strip()

    # Редот е важен - поспецифичните прво
    # ВАЖНО: "тргни оцена" мора пред "оцени" (има збор „оцена" во двете)
    if _ima_zbor(p, KLUCNI_TRGNI_OCENA):
        return "trgni_ocena"

    if _ima_zbor(p, KLUCNI_OCENI):
        return "oceni_pregled"

    if _ima_zbor(p, KLUCNI_POTSETNIK):
        return "postavi_potsetnik"

    if _ima_zbor(p, KLUCNI_PRENESI):
        return "prenesi_termin"

    # „откажи" пред „закажи" зашто се преклопуваат како почеток
    if _ima_zbor(p, KLUCNI_OTKAZI):
        return "otkazi_termin"

    if _ima_zbor(p, KLUCNI_ZAKAZI):
        return "zakazi_termin"

    if _ima_zbor(p, KLUCNI_PREPORAKA):
        return "preporaka_lekar"

    if _ima_zbor(p, KLUCNI_RABOTNO):
        return "rabotno_vreme"

    if _ima_zbor(p, KLUCNI_LOKACIJA):
        return "lokacija"

    if _ima_zbor(p, KLUCNI_KONTAKTI):
        return "kontakti"

    if _ima_zbor(p, KLUCNI_USLUGI):
        return "uslugi"

    if _ima_zbor(p, KLUCNI_INFO_LEKAR):
        return "info_lekar"

    if _ima_zbor(p, KLUCNI_SLOBODNI):
        return "slobodni_termini"

    return None  # нема jasen keyword match


def detektiraj_intent(prashanje: str) -> str:
    """
    Главна функција - хибриден пристап.

    1. Проба со keyword detector (брзо, бесплатно).
    2. Ако не најде → AI (Groq) за природни варијации.
    3. Ако и AI не успее → "general".
    """
    if not prashanje:
        return "general"

    # Чекор 1: keyword detector со транслитерација
    intent = detektiraj_intent_keyword(prashanje)
    if intent:
        return intent

    # Чекор 2: AI fallback - проба со Groq
    try:
        ai_intent = detektiraj_intent_so_ai(prashanje)
        if ai_intent:
            return ai_intent
    except Exception as e:
        print(f"[intent_detector] AI fallback greshka: {e}")

    return "general"
