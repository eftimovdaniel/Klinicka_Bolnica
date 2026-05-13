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
- "objavi_vest"       → објави вест од YouTube линк (само директор)
- "kreiraj_oglas"     → креирај оглас за работа (само директор)
- "izbrisi_vest_oglas"→ избриши вест или оглас (само директор)
- "zatvori_oglas"     → затвори оглас (status=истечен) (само директор)
- "promeni_dezurstvo" → промени дежурство на лекар (само директор)
- "statistika_oddeli" → анализа на најпопуларни оддели (само директор)
- "zavrshi_pregled"   → заврши преглед како „завршен" (лекар)
- "istorija_pacient"  → историја на пациент кај овој лекар (лекар)
- "karton_pacient"    → медицински картон на пациент (лекар)
- "moja_statistika"   → лични статистики на лекар (лекар)
- "moj_raspored"      → распоред на закажани прегледи (лекар)
- "general"           → одговор од AI за општо прашање

ВАЖНО: Редот на проверки е важен (поспецифичните прво).
"""


# 00. ОБЈАВИ ВЕСТ (мора први - има YouTube линк или зборови за публикување)
KLUCNI_OBJAVI_VEST = [
    "објави вест", "објави новост", "публикувај",
    "креирај вест", "создади вест", "напиши вест",
    "новост од видео", "вест од видео", "вест од youtube",
    "youtube линк", "ютуб линк",
    "ставете на сајт", "стави на сајт",
    # Англиски и латиница за директорот
    "objavi vest", "publish news", "post news",
]

# 00b. КРЕИРАЈ ОГЛАС ЗА РАБОТА (за директор)
KLUCNI_OGLAS = [
    "креирај оглас", "создај оглас", "напиши оглас",
    "објави оглас", "нов оглас", "оглас за работа",
    "оглас за вработување", "стави оглас",
    "сакам да објавам оглас", "сакам да креирам оглас",
    # Латиница
    "kreiraj oglas", "novo oglas", "objavi oglas",
]

# 00c. ИЗБРИШИ ВЕСТ / ОГЛАС (за директор) – мора пред trgni_ocena
KLUCNI_IZBRISI_VEST_OGLAS = [
    "избриши вест", "избриши ја вест", "избриши новост", "избриши ја новост",
    "избриши го најновиот оглас", "избриши го последниот оглас",
    "избриши го огласот", "избриши оглас",
    "тргни вест", "тргни оглас", "отстрани вест", "отстрани оглас",
    "delete vest", "delete oglas", "izbrisi vest", "izbrisi oglas",
]

# 00d. ЗАТВОРИ ОГЛАС (за директор) – status=истечен
KLUCNI_ZATVORI_OGLAS = [
    "затвори оглас", "затвори го оглас", "затвори ги огласите",
    "истечен оглас", "истечен е оглас", "стави го оглас како истечен",
    "оглас како истечен", "огласот е истечен",
    "deaktiviraj oglas", "deaktiviraj go oglasot",
]

# 00e. ПРОМЕНИ ДЕЖУРСТВО (за директор)
KLUCNI_DEZURSTVO = [
    "дежурство", "дежурствата", "дежурствата на",
    "префрли дежурство", "премести дежурство", "промени дежурство",
    "пренеси дежурство", "одложи дежурство",
    "промени го дежурството", "префрли го дежурството",
    "deziurstvo", "promeni dezurstvo",
]

# 00f. СТАТИСТИКА НА ОДДЕЛИ (за директор)
KLUCNI_STATISTIKA = [
    "најпопуларни оддели", "најпопуларни оддел",
    "топ оддели", "топ оддел", "топ специјалности", "топ специјалност",
    "анализа на оддели", "анализа на специјалности",
    "колку прегледи по оддел", "статистика на оддели",
    "најпосетени оддели", "најпосетени специјалности",
    "popularni oddeli", "top oddeli", "statistika oddeli",
]

# 00g. ЗАВРШИ ПРЕГЛЕД (лекар) - мора пред „zakazi_termin" зашто содржи „преглед"
KLUCNI_ZAVRSHI = [
    "заврши преглед", "заврши го прегледот", "заврши го терминот",
    "заврши термин", "заврши го",
    "означи како завршен", "означи го прегледот", "финализирај преглед",
    "пациентот заврши", "прегледот заврши",
    "complete pregled", "zavrshi pregled", "zavrshi termin",
]

# 00h. ИСТОРИЈА НА ПАЦИЕНТ (лекар)
KLUCNI_ISTORIJA = [
    "историја на пациент", "историја на",
    "колку пати беше", "колку пати дојде",
    "историја кај мене", "колку прегледи имаше",
    "istorija pacient",
]

# 00i. КАРТОН НА ПАЦИЕНТ (лекар)
KLUCNI_KARTON = [
    "картон", "медицински картон",
    "досие", "медицинско досие",
    "дај ми картон", "покажи картон",
    "karton pacient",
]

# 00j. МОИ СТАТИСТИКИ (лекар)
KLUCNI_MOJA_STATISTIKA = [
    "мои статистики", "моите статистики",
    "колку прегледи имам", "колку имам прегледи",
    "просечна оцена", "просечната оцена",
    "каква ми е оцената", "моите оцени",
    "моја статистика", "мој рејтинг",
    "moja statistika", "moi statistiki",
]

# 00k. МОЈ РАСПОРЕД (лекар) – мора пред „zakazi_termin"
KLUCNI_RASPORED = [
    "распоред", "распоредот", "мој распоред", "мојот распоред",
    "закажани прегледи", "закажаните прегледи",
    "закажани термини", "закажаните термини",
    "моите прегледи", "моите закажани", "моите термини",
    "прикажи прегледи", "прикажи закажани", "покажи прегледи",
    "прикажи ги моите", "покажи ги моите",
    "следни прегледи", "следните прегледи",
    "идни прегледи", "идните прегледи",
    "што имам утре", "што имам денес", "што имам наредно",
    "кои се моите следни", "кои ми се идните",
    "moj raspored", "raspored",
]

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

    # ВРВ (пред транслитерација): провери за YouTube линк во оригинален текст
    # (трансли. би ги претворила www.youtube.com → ввв.јоутубе.цом)
    orig_low = prashanje.lower().strip()
    if "youtube.com" in orig_low or "youtu.be" in orig_low:
        return "objavi_vest"

    # Автоматски преводи: латиница → кирилица
    p = transliterijaj(prashanje).lower().strip()

    if _ima_zbor(p, KLUCNI_OBJAVI_VEST):
        return "objavi_vest"

    # ВАЖНО: „избриши" + („вест"/„оглас"/„новост") во истиот текст
    # → флексибилно совпаѓање, дури и ако има зборови помеѓу
    # (пр. „избриши ја најновата вест")
    ima_brisi = any(w in p for w in ("избриши", "тргни", "отстрани", "izbrisi", "delete"))
    ima_vest_ili_oglas = any(w in p for w in ("вест", "новост", "оглас", "vest", "novost", "oglas"))
    # за да не се коли со trgni_ocena → исклучи ако има „оцена"
    if ima_brisi and ima_vest_ili_oglas and "оцен" not in p:
        return "izbrisi_vest_oglas"

    if _ima_zbor(p, KLUCNI_IZBRISI_VEST_OGLAS):
        return "izbrisi_vest_oglas"

    # ВАЖНО: „затвори оглас" мора пред „kreiraj_oglas"
    if _ima_zbor(p, KLUCNI_ZATVORI_OGLAS):
        return "zatvori_oglas"

    # Статистика на оддели мора ПРЕД „uslugi" (зашто „специјалности" е во двете)
    # Флексибилно: „топ" + („оддел"/„специјал") во истиот текст
    if "топ" in p and any(w in p for w in ("оддел", "специјал")):
        return "statistika_oddeli"
    if _ima_zbor(p, KLUCNI_STATISTIKA):
        return "statistika_oddeli"

    if _ima_zbor(p, KLUCNI_OGLAS):
        return "kreiraj_oglas"

    # Дежурства на оддели (за директор)
    if _ima_zbor(p, KLUCNI_DEZURSTVO):
        return "promeni_dezurstvo"

    # ВАЖНО: D1 „заврши преглед" мора пред zakazi/otkazi/prenesi (со „преглед")
    if _ima_zbor(p, KLUCNI_ZAVRSHI):
        return "zavrshi_pregled"

    # B1 „мој распоред" / „закажаните прегледи" - мора пред zakazi_termin
    if _ima_zbor(p, KLUCNI_RASPORED):
        return "moj_raspored"

    # D3 „картон" има специфичен збор кој не се преклопува
    if _ima_zbor(p, KLUCNI_KARTON):
        return "karton_pacient"

    # D2 „историја на пациент"
    if _ima_zbor(p, KLUCNI_ISTORIJA):
        return "istorija_pacient"

    # D4 „мои статистики" / „просечна оцена" - мора пред oceni_pregled
    if _ima_zbor(p, KLUCNI_MOJA_STATISTIKA):
        return "moja_statistika"

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
