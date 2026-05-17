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
- "lekari_oddel"      → листа на лекари по оддел / специјалност
- "preporaka_lekar"   → препорака според симптом
- "rabotno_vreme"     → работно време
- "lokacija"          → локации на оддели
- "kontakti"          → контакти на болницата
- "uslugi"            → список на услуги
- "objavi_vest"       → објави вест од YouTube линк (само директор)
- "kreiraj_oglas"     → креирај оглас за работа (само директор)
- "izbrisi_vest_oglas"→ избриши вест или оглас (само директор)
- "zatvori_oglas"     → затвори оглас (status=истечен) (само директор)
- "pregled_dezurstvo" → кога е дежурен лекар (листа идни дежурства)
- "promeni_dezurstvo" → промени дежурство на лекар (само директор)
- "statistika_oddeli" → анализа на најпопуларни оддели (само директор)
- "zavrshi_pregled"   → заврши преглед како „завршен" (лекар)
- "istorija_pacient"  → историја на пациент кај овој лекар (лекар)
- "karton_pacient"    → медицински картон на пациент (лекар)
- "moja_statistika"   → лични статистики на лекар (лекар)
- "moj_raspored"      → распоред на закажани прегледи (лекар)
- "navigacija"        → пренасочи на секција од сајтот
- "apliciraj_za_rabota" → AI агент аплицира за работа за пациент (повеќестепен)
- "moi_pregledi"      → пациент: историја и идни прегледи
- "aplikanti_oglas"   → директор: листа на апликанти за оглас
- "zapishi_terapija"  → лекар: запиши терапија/дијагноза на пациент
- "novosti_rezime"    → краток преглед на последните новости (наслови + линк)
- "faq_pregled"       → подготовка за преглед (гладно, што да понесам — од JSON)
- "rezultati_testovi" → кога се готови резултати од тестови
- "preference_lekar"  → преференција за лекар (пол, јазик, искуство)
- "izvestaj_den_nedela" → дневен/неделен извештај за термини и апликации (само директор)
- "otvori_admin_panel" → отвори административен панел на сајтот (само директор)
- "general"           → одговор од AI за општо прашање

ВАЖНО: Редот на проверки е важен (поспецифичните прво).
"""


# 00. ОБЈАВИ ВЕСТ (мора први - има YouTube линк или зборови за публикување)
KLUCNI_OBJAVI_VEST = [
    "објави вест", "објави новост", "објави ја", "објави ја следната",
    "следната вест", "вест на сајт", "вест на сајтот",
    "публикувај", "креирај вест", "создади вест", "напиши вест",
    "новост од видео", "вест од видео", "вест од youtube",
    "youtube линк", "ютуб линк",
    "ставете на сајт", "стави на сајт",
    "objavi vest", "objavi ja", "slednata vest", "vest na sajtot",
    "publish news", "post news",
]


def prasanje_ima_youtube_link(prasanje: str) -> bool:
    """YouTube URL — не транслитерирај (ниту проверувај по нормализиран јоутубе.цом)."""
    t = (prasanje or "").lower()
    return "youtube.com" in t or "youtu.be" in t

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
    "избриши ја веста со наслов", "избриши веста со наслов",
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

# 00d2. ПРЕГЛЕД ДЕЖУРСТВА (кога е дежурен лекар — пред промена)
KLUCNI_PREGLED_DEZURSTVO = [
    "кога е дежур", "кога е на дежур", "кога дежур",
    "кога има дежур", "дали е дежур", "дали е на дежур",
    "дали има дежур", "има дежурства", "има дежурство",
    "кој ден е дежур", "кога работи на дежур",
    "распоред на дежур", "идни дежурства", "наредниот период",
    "koga e dezur", "koga e na dezur", "dali e dezurna", "dali ima dezur",
]

# 00e. ПРОМЕНИ ДЕЖУРСТВО (за директор)
KLUCNI_DEZURSTVO = [
    "дежурство", "дежурствата", "дежурствата на",
    "додади дежурство", "додадете дежурство", "внеси дежурство",
    "дежурна на", "да биде дежурна",
    "префрли дежурство", "премести дежурство", "промени дежурство",
    "пренеси дежурство", "одложи дежурство",
    "промени го дежурството", "префрли го дежурството",
    "промени", "промениш", "може да го промениш", "смени",
    "deziurstvo", "promeni dezurstvo",
]

# 00e2. ОТВОРИ АДМИН ПАНЕЛ (директор)
KLUCNI_OTVORI_ADMIN = [
    "административен панел",
    "административниот панел",
    "административниот",
    "админ панел",
    "admin panel",
    "отвори администрација",
    "отвори ја администрацијата",
    "прикажи администрација",
    "прикажи ја администрацијата",
    "прикажи го административниот",
    "однеси ме на администрација",
    "однеси на админ",
    "во административниот панел",
    "во админ панел",
    "otvori admin",
    "prikazi admin",
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

# 00l. НАВИГАЦИЈА (за сите – пренасочи на секција)
KLUCNI_NAVIGACIJA = [
    "однеси ме", "одведи ме", "однеси me", "однеси",
    "каде се лекарите", "каде се лекарите", "каде се докторите",
    "каде е лекарите", "каде се наоѓаат лекарите", "каде се наоѓаат докторите",
    "kade se lekarite", "kade se lekarite", "kade se doktorite",
    "покажи ми ги лекарите", "прикажи ми ги лекарите",
    "дај ми ги сите лекари", "сите лекари во болницата",
    "лекари работат во болниц", "доктори работат во болниц",
    "лекари во болницата", "доктори во болницата",
    "во оваа установа", "во установата",
    "медицински тим", "тимот на болницата",
    "покажи услуги", "прикажи услуги", "однеси на услуги",
    "покажи новости", "прикажи новости", "однеси на новости",
    "покажи кариера", "прикажи кариера", "однеси на кариера",
    "сите кариери", "дај ми кариера", "види кариера",
    "слободни позиции", "слободни работни места", "работни места",
    "имате ли работа", "имате работа", "имате ли вработување",
    "има ли работа", "има ли вработување", "дали има работа",
    "ima li rabota", "dali ima rabota",
    "сите огласи", "сите огласи за работа", "огласи за работа",
    "сите вработувања", "вработување во болницата",
    "сите вести", "сите новости",
    "однеси на контакт", "прикажи контакт",
    "почетна страна", "главна страна",
    "navigacija",
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
    "откажи",
    "откажеш",
    "откажам",
    "откажете",
    "откажување",
    "откажува",
    "го откажи",
    "го откажеш",
    "да го откажеш",
    "може да го откажеш",
    "може да го откажам",
    "сторнирај",
    "сторно",
    "поништи термин",
    "не сакам термин",
    "не доаѓам",
    "cancel termin",
]

# 1. ЗАКАЖУВАЊЕ (иста намера — различни формулации)
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
    "направи ми термин", "направете ми термин", "направи термин",
    "одреди ми термин", "одреди термин", "закажи ми",
    "сакам да одам кај", "сакам да одам на преглед", "сакам да видам",
    "би сакал да закажам", "би сакала да закажам",
    "закажување на преглед", "закажување на термин",
    "termin za", "zakazi termin", "sakam da zakazam", "zapisi me",
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
    "работно време",
    "работното време",
    "работно време на",
    "работното време на",
    "кое е работно",
    "ко е работното",
    "кога е отворен",
    "кога е отворено",
    "кога работи болницата",
    "кога ради болницата",
    "кога е затворен",
    "работни денови",
    "rabotno vreme",
    "rabotnoto vreme",
]

# 5. ЛОКАЦИЈА (без „каде е" само — меша се со „каде е контакт?")
KLUCNI_LOKACIJA = [
    "каде се наоѓа",
    "каде се наоѓаат",
    "локација",
    "локацијата",
    "како да дојдам",
    "како да стигнам",
    "во кој спрат",
    "кој спрат",
    "соба",
    "каде е оддел",
    "каде е гинеколог",
    "каде е кардиолог",
    "каде е лаборатор",
    "каде е итна",
    "kade se naogja",
    "lokacija",
]

# 6. КОНТАКТИ (пред локација во редот на проверки)
KLUCNI_KONTAKTI = [
    "телефон", "тел ", "контакт", "контакти",
    "каде е контакт", "каде е контактот", "kade e kontakt",
    "на кој број", "кој број", "бројот на",
    "како да јавам", "како да повикам", "како да се јавам",
    "итна помош", "итен", "итна", "ургентно",
    "email", "е-пошта", "e-posta", "mail",
    "рецепција", "recepcija", "централа",
]

# 7. УСЛУГИ
KLUCNI_USLUGI = [
    "услуги", "услугите", "какви услуги",
    "што нудите", "што имате",
    "специјалности", "оддели",
]

# 7b. АСИСТЕНТ / ПОЗДРАВ / ИДЕНТИТЕТ → general (не info_lekar)
KLUCNI_ASISTENT_OPSTO = [
    "кој си", "кој сте", "ко си", "ти кој си", "што си", "што сте",
    "како се викаш", "како те викат", "кое е твоето име", "твоето име",
    "дали си вистински", "дали си бот", "дали си ai", "дали си робот",
    "што правиш", "што можеш", "како работиш", "како можеш да помогнеш",
    "здраво", "добар ден", "добро утро", "добровече", "поздрав", "чао",
    "благодарам", "фала", "thanks", "thank you",
    "hello", "hi ", "hey ",
    "koj si", "koi si", "sto si", "zdravo", "pozdrav", "dobar den",
]

# 8. ИНФО ЗА ЛЕКАР (без „каков е" само — меша се со телефон/контакт)
KLUCNI_INFO_LEKAR = [
    "информации за", "инфо за", "повеќе за",
    "опис на лекар",
    "дали работи", "дали е вработен", "работи ли",
    "работи тука", "работи во болницата", "работи во оваа болница",
    "има ли тука", "дали е тука", "дали е во болницата",
    "dali raboti", "raboti li",
    "koi e dr", "кој е д-р", "кој е др",
]

# Зборови што НЕ се имиња на лекари (info_lekar false positive)
_ZBOROVI_NE_SE_IMENA = frozenset(
    {
        "каков",
        "каква",
        "кој",
        "кое",
        "ко",
        "телефон",
        "телефонот",
        "контакт",
        "контактот",
        "контакти",
        "email",
        "mail",
        "е-пошта",
        "рецепција",
        "централа",
        "болница",
        "болницата",
        "клиничка",
        "клиничката",
        "штип",
        "stip",
        "нова",
        "nova",
        "опрема",
        "oprema",
        "вест",
        "веста",
        "новост",
        "новоста",
        "наслов",
        "работно",
        "работното",
        "време",
        "локација",
        "локацијата",
        "наоѓа",
        "наоѓаат",
        "каде",
        "оддел",
        "услуги",
        "услугите",
        "kontakt",
        "telefon",
        "kakov",
        "koe",
        "си",
        "ти",
        "те",
        "мене",
        "вие",
        "нас",
        "вас",
        "себе",
        "si",
        "ti",
    }
)

# 8c. МОИТЕ ПРЕГЛЕДИ (пациент)
KLUCNI_MOI_PREGLEDI = [
    "моите прегледи", "моите пргледи", "историја на прегледи",
    "историја на моите", "сите мои прегледи",
    "идни прегледи", "минати прегледи",
    "прикажи ми ги прегледите", "прикажи ми ги моите прегледи",
    "колку прегледи имам", "кои се моите прегледи",
    "moite pregledi", "moi pregledi", "istorija na pregledi",
]

# 8c2. РЕЗИМЕ НА НОВОСТИ (краток текст од база, не навигација)
KLUCNI_REZIME_NOVOSTI = [
    "резиме на новости", "резиме на вести", "наслови на новости", "последни наслови",
    "најнови наслови", "сумирај ги новостите", "новости накратко", "вести накратко",
    "што има ново", "што е ново", "najnovi naslovi", "rezime na novosti",
    "последни новости", "најнови вести", "краток преглед на новости",
]

# 8c2b. РЕЗУЛТАТИ ОД ТЕСТОВИ (мора пред FAQ — „крвна" може да се меша)
KLUCNI_REZULTATI = [
    "кога ќе готов", "кога ke gotov", "готов ли е", "gotov li e",
    "резултат", "rezultat", "извештај", "izveshtaj", "лабораторија врати",
    "кога ќе имам", "кога ke imam", "подигнување резултат", "online резултат",
    "email резултат", "резултати од", "анализи кога",
]

# 8c2c. ПРЕФЕРЕНЦИ ЗА ЛЕКАР
KLUCNI_PREFERENCE = [
    "женски лекар", "женска докторка", "женски кардиолог", "женски невролог",
    "zenski lekar", "zenski kardiolog",
    "машки лекар", "maski lekar",
    "има ли женски", "ima li zenski", "има ли машки",
    "кој зборува англиски", "angliski", "англиски",
    "со искуство", "млад лекар", "постар лекар",
    "детска кардиологија", "детски лекар",
]

# 8c3. FAQ подготовка за преглед (од JSON; не симптоми)
KLUCNI_FAQ_PREGLED = [
    "гладно", "на гладно", "на пост", "постот", "јадење пред", "јаденje пред",
    "што да понесам", "што да донесам", "подготовка за преглед", "пред преглед",
    "лична карта", "здравствена книшка", "лекови пред", "дали да пијам лекови",
    "доцнење на термин", "што ако доцнам", "gladno", "ponesam", "donesam",
    "придружител", "бремена", "прва посета", "фотографија",
]

# 8c4. ДНЕВЕН/НЕДЕЛЕН ИЗВЕШТАЈ (директор) — пред „апликаци" за apliciraj
KLUCNI_DNEVEN_IZVESTAJ = [
    "извештај за денес", "извештај денес", "дневен извештај", "дневен преглед",
    "извештај за оваа недела", "неделен извештај", "извештај за неделата",
    "колку термини денес", "термини денес", "статистика за денес",
    "статистика за недела", "преглед на термини",
    "dneven izveshtaj", "izveshtaj denes", "nedelen izveshtaj",
]

# 8d. АПЛИКАНТИ ЗА ОГЛАС (директор)
KLUCNI_APLIKANTI = [
    "апликанти", "апликантите", "кандидати за оглас", "кандидатите",
    "пријавени лекари", "пријавени за оглас", "кои се пријавиле",
    "кој се аплицирал", "кој аплицира", "пријавени кандидати",
    "aplikanti", "kandidati", "prijaveni lekari",
]

# 8e. ЗАПИШИ ТЕРАПИЈА (лекар)
KLUCNI_ZAPISHI_TERAPIJA = [
    "запиши терапија", "запиши терапии", "запиши дијагноза",
    "додај терапија", "додади терапија",
    "пропиши терапија", "пропиши лек",
    "терапија за", "терапија на",
    "дијагноза за", "дијагноза на",
    "евидентирај терапија",
    "zapisi terapija", "dodaj terapija", "propisi terapija",
]

# 8b. ЛЕКАРИ ПО ОДДЕЛ – „кои лекари се на одделот за Х"
KLUCNI_LEKARI_ODDEL = [
    "кои лекари се на",
    "кои се лекарите од",
    "кои се лекарите на",
    "кои лекари се од",
    "кои лекари работат на",
    "кои доктори се на",
    "кои се од",
    "кои лекари има на",
    "кои лекари има во",
    "докторите од",
    "докторите на",
    "лекарите од",
    "лекарите на",
    "други лекари",
    "друг лекар",
    "уште лекари",
    "истата специјалност",
    "оваа специјалност",
    "истиот оддел",
    "оваа специјалности",
    "koi lekari se na",
    "koi se lekarite od",
    "drugi lekari",
    "лекари по",
    "лекари од",
    "прикажи ми лекари",
    "прикази ми лекари",
    "покажи ми лекари",
    "лекари од областа",
    "на одделот",
    "одделот за",
    "lekari po",
    "lekari od",
]

# 9. СЛОБОДНИ ТЕРМИНИ (исто прашање — различни начини)
KLUCNI_SLOBODNI = [
    "слободен", "слободна", "слободни", "слободно",
    "кога е слободен", "кога е слободна",
    "кога ради", "кога работи",
    "слободни термини", "слободен термин", "слободни часови",
    "има ли термин", "има ли слободно", "има ли место",
    "кога можам", "кога може", "во кое време можам",
    "провери", "провер", "може да провер",
    "наредниот", "нареден", "наредна", "следниот", "следен",
    "прв слободен", "прва слободна", "најбрз термин",
    "достапни термини", "достапен термин", "достапност",
    "кога има место", "кога има термин",
    "распоред кај", "термини кај", "преглед кај",
    "slobodni termini", "koga e sloboden", "ima li termin",
]


import re

from ai._kernel.transliteracija import transliterijaj
from ai._kernel.ai_intent_detector import detektiraj_intent_so_ai


def _ima_zbor(prasanje: str, kluchni: list[str]) -> bool:
    """Помошна функција - проверка на клучни зборови."""
    return any(zbor in prasanje for zbor in kluchni)


def _prasanje_e_rabotno_vreme(p: str) -> bool:
    """
    Работно време на болница/оддел — не конкретен лекар.
    „Кое е работното време на болницата?" мора да не оди на info_lekar.
    """
    if any(
        w in p
        for w in (
            "следен работен",
            "следниот работен",
            "нареден работен",
            "наредниот работен",
            "прв работен ден",
            "кога е работен ден",
        )
    ):
        return False
    if _ima_zbor(p, KLUCNI_RABOTNO):
        return True
    if re.search(r"работн\w*\s+време", p):
        return True
    if "време" in p and any(w in p for w in ("работн", "rabotn", "отворен", "затворен")):
        if any(w in p for w in ("болниц", "оддел", "рецепци", "прием", "итна", "лаборатор")):
            return True
    return False


def _prasanje_e_lokacija_oddel(p: str) -> bool:
    """
    Локација на оддел/специјалност — не конкретен лекар по име.
    „Каде се наоѓа кардиологијата?" → lokacija, не info_lekar.
    """
    if _prasanje_e_kontakti(p):
        return False
    if _ima_zbor(p, KLUCNI_LOKACIJA):
        return True
    if any(x in p for x in ("каде е", "каде se", "kade e", "каде се", "kade se")):
        if any(
            x in p
            for x in (
                "наоѓа",
                "naogja",
                "локаци",
                "lokaci",
                "спрат",
                "соба",
                "оддел",
                "дојдам",
                "стигнам",
            )
        ):
            return True
        if any(
            x in p
            for x in (
                "гинеколог",
                "кардиолог",
                "невролог",
                "уролог",
                "ортопед",
                "лаборатор",
                "радиолог",
                "итна",
                "аптека",
                "хирург",
                "педиатр",
                "онколог",
                "интерна",
            )
        ):
            return True
    return False


def _prasanje_e_asistent_opsto(p: str) -> bool:
    """Прашања за асистентот, не за лекар во база."""
    if _ima_zbor(p, KLUCNI_ASISTENT_OPSTO):
        return True
    if re.search(
        r"\b(кој|koi|ko)\s+(си|си\s+ти|ste|si|e\s+ти)\b",
        p,
        re.UNICODE,
    ):
        return True
    if re.search(
        r"\b(што|sto|what)\s+(си|сме|ste|are|правиш|pravish|можеш)\b",
        p,
        re.UNICODE,
    ):
        return True
    if re.search(r"\b(здраво|zdravo|поздрав|pozdrav|hello|hey)\b", p, re.UNICODE):
        return True
    return False


def _prasanje_e_konkreten_lekar(prasanje: str) -> bool:
    """
    Прашање за конкретен лекар по име (не листа/навигација).
    Пр. „Дали работи др Марија Хубрева?", „Кој е д-р Петров?"
    """
    from ai._kernel.lekar_lookup import izvlechi_delovi_ime

    p = transliterijaj(prasanje).lower()
    if _prasanje_e_asistent_opsto(p):
        return False
    if prasanje_ima_youtube_link(prasanje) or _ima_zbor(p, KLUCNI_OBJAVI_VEST):
        return False
    if _bolnica_info_intent(p):
        return False
    if _ima_zbor(p, KLUCNI_SLOBODNI):
        return False
    if any(w in p for w in ("кои лекари", "кои доктори", "лекари на", "лекари од")):
        return False
    try:
        from ai.opsto.lekari_oddel import prasanje_e_lekari_po_oddel
        from ai.opsto.vest_naslov import (
            prasanje_e_izbrisi_vest_oglas,
            prasanje_e_samo_naslov_vest,
        )
        from ai.pacient.slobodni_termini import prasanje_e_ko_e_sloboden_datum_vreme

        if prasanje_e_lekari_po_oddel(prasanje):
            return False
        if prasanje_e_ko_e_sloboden_datum_vreme(prasanje):
            return False
        if prasanje_e_izbrisi_vest_oglas(prasanje) or prasanje_e_samo_naslov_vest(prasanje):
            return False
    except ImportError:
        pass
    delovi = izvlechi_delovi_ime(prasanje)
    if _delovi_izgledaat_kako_ime(delovi):
        return True
    if len(delovi) == 1 and delovi[0] not in _ZBOROVI_NE_SE_IMENA:
        if re.search(r"\b(д-р|др|dr)\b", p, re.UNICODE):
            return True
    return False


def _bolnica_info_intent(p: str) -> str | None:
    """Општи информации за болницата — никогаш info_lekar."""
    if _prasanje_e_kontakti(p):
        return "kontakti"
    if _prasanje_e_rabotno_vreme(p):
        return "rabotno_vreme"
    if _prasanje_e_lokacija_oddel(p):
        return "lokacija"
    if _ima_zbor(p, KLUCNI_USLUGI):
        return "uslugi"
    return None


def _ima_kluc_info_lekar(p: str) -> bool:
    """Клучни зборови за лекар — не ако прашањето е за контакт/време/локација."""
    if _prasanje_e_asistent_opsto(p):
        return False
    if _bolnica_info_intent(p):
        return False
    if _ima_zbor(p, KLUCNI_INFO_LEKAR):
        return True
    if re.search(r"\b(каков\w*|каква\w*|кој)\s+е\b", p) and any(
        w in p for w in ("лекар", "д-р", " др", "доктор", "lekар", "dr ", "d-r")
    ):
        return True
    return False


def _delovi_izgledaat_kako_ime(delovi: list[str]) -> bool:
    """Дали извлечените зборови личат на име/презиме, не на „телефон/контакт"."""
    smisleni = [d for d in delovi if d not in _ZBOROVI_NE_SE_IMENA]
    return len(smisleni) >= 2


def _prasanje_e_kontakti(p: str) -> bool:
    """Телефон/контакт/мејл — не локација на оддел (на пр. „Каде е контакт?")."""
    if any(
        x in p
        for x in (
            "контакт",
            "контакти",
            "телефон",
            "телефонот",
            "тел.",
            "kontakt",
            "telefon",
            "email",
            "е-пошта",
            "e-posta",
            "рецепци",
            "recepc",
            "централа",
            "за контакт",
            "за kontakt",
        )
    ):
        return True
    if "број" in p and any(
        x in p for x in ("јавам", "повикам", "повик", "телефон", "рецепци")
    ):
        return True
    if "итн" in p and any(x in p for x in ("помош", "број", "телефон", "повик")):
        return True
    return False


def _baranje_e_promena_dezurstvo(p: str) -> bool:
    """Додади / премести / промени — не е само прашање „кога е дежурна"."""
    return any(
        w in p
        for w in (
            "додади",
            "dodadi",
            "додадете",
            "внеси",
            "закажи дежур",
            "премести",
            "префрли",
            "промени дежур",
            "промени",
            "промениш",
            "пренеси дежур",
            "одложи дежур",
            "смени",
            "може да го промениш",
            "да биде дежурна на",
            "дежурна на",
            "promeni dezur",
        )
    )


def _prasanje_e_pregled_dezurstvo(p: str) -> bool:
    if _baranje_e_promena_dezurstvo(p):
        return False
    if _ima_zbor(p, KLUCNI_PREGLED_DEZURSTVO):
        return True
    if "дежур" in p and any(
        w in p for w in ("кога", "koga", "дали", "dali", "кој ден", "koj den")
    ):
        return True
    return False


def _tekst_e_oglas_za_objava(p: str) -> bool:
    """
    Текст на оглас што директорот објавува (не барање „сакам да аплицирам").
    „можност за аплицирање до …" = рок за кандидати, не intent за apliciraj.
    """
    if any(x in p for x in ("оглас за работа", "oglas za rabota")):
        return True
    if any(x in p for x in ("се вработува", "se vrabotuva", "ќе се вработи")):
        return True
    if "можност за аплицирање" in p or "moznost za apliciranje" in p:
        if any(
            x in p
            for x in (
                "персонал",
                "медицинск",
                "сестр",
                "одделот",
                "оддел",
                "гинекол",
                "гиникол",
                "акауш",
            )
        ):
            return True
    return False


def detektiraj_intent_keyword(prasanje: str) -> str | None:
    """
    Брза проверка преку клучни зборови.
    Враќа: име на интент ИЛИ None ако нема јасно совпаѓање.
    """
    if not prasanje:
        return None

    if prasanje_ima_youtube_link(prasanje):
        return "objavi_vest"

    # Автоматски преводи: латиница → кирилица
    p = transliterijaj(prasanje).lower().strip()

    if _prasanje_e_asistent_opsto(p):
        return "general"

    # Директор: креирај / објави оглас (пред navigacija и apliciraj)
    if any(
        w in p
        for w in (
            "креирај оглас",
            "kreiraj oglas",
            "објави оглас",
            "objavi oglas",
            "направи оглас",
            "napravi oglas",
            "стави оглас",
            "nov oglas",
            "нов оглас",
        )
    ):
        return "kreiraj_oglas"
    if p in ("оглас за работа", "oglas za rabota", "оглас за rabota"):
        return "kreiraj_oglas"

    # Залепен текст на оглас → директор го објавува (kreiraj_oglas), не аплицирање
    if _tekst_e_oglas_za_objava(p):
        return "kreiraj_oglas"

    if _ima_zbor(p, KLUCNI_OBJAVI_VEST):
        return "objavi_vest"

    try:
        from ai.opsto.vest_naslov import prasanje_e_izbrisi_vest_oglas

        if prasanje_e_izbrisi_vest_oglas(prasanje) and "оцен" not in p:
            return "izbrisi_vest_oglas"
    except ImportError:
        ima_brisi = any(
            w in p
            for w in (
                "избриши",
                "избришете",
                "тргни",
                "отстрани",
                "izbrisi",
                "delete",
            )
        )
        ima_vest_ili_oglas = any(
            w in p for w in ("вест", "новост", "оглас", "vest", "novost", "oglas")
        )
        if ima_brisi and ima_vest_ili_oglas and "оцен" not in p:
            return "izbrisi_vest_oglas"

    if _ima_zbor(p, KLUCNI_IZBRISI_VEST_OGLAS):
        return "izbrisi_vest_oglas"

    # ВАЖНО: „затвори оглас" мора пред „kreiraj_oglas"
    if _ima_zbor(p, KLUCNI_ZATVORI_OGLAS):
        return "zatvori_oglas"

    # Флексибилно: „затвори/затвор" + („оглас") во истиот текст
    # (пр. „затвори активен оглас", „затвори го огласот")
    if any(w in p for w in ("затвори", "затвор", "zatvori")) and (
        "оглас" in p or "oglas" in p
    ):
        return "zatvori_oglas"

    # Статистика на оддели мора ПРЕД „uslugi" (зашто „специјалности" е во двете)
    # Флексибилно: „топ" + („оддел"/„специјал") во истиот текст
    if "топ" in p and any(w in p for w in ("оддел", "специјал")):
        return "statistika_oddeli"
    if _ima_zbor(p, KLUCNI_STATISTIKA):
        return "statistika_oddeli"

    # Навигација кон „кариера" – мора ПРЕД KLUCNI_OGLAS, зашто
    # „оглас за работа" е во двата (но „креирај/нов/објави/стави" е само за креирање)
    KREIRAJ_RECI = (
        "креирај", "создај", "напиши", "објави", "стави оглас", "нов оглас",
        "нова позиција", "сакам да објавам", "сакам да креирам",
        "kreiraj", "objavi", "stavi oglas", "novo oglas", "novo rabotno"
    )
    ima_kreiraj = any(w in p for w in KREIRAJ_RECI)

    # Дирекно „кариер/вработувањ/слободни работни/работни позиции" – секогаш навигација
    if not ima_kreiraj and any(w in p for w in (
        "кариер", "вработувањ", "вработување",
        "слободни позиции", "слободни работни", "работни места",
        "работни позиции", "работна позиција",
        "kariera", "vrabotuvanje", "vrabotuvanj",
        "rabotni pozicii", "rabotna pozicija",
    )):
        return "navigacija"

    # Флексибилно: „позиц" + („отворен/слобод/актив/работн/нови")
    # (пр. „има ли отворени позиции", „кои позиции се отворени")
    if not ima_kreiraj and "позиц" in p and any(
        w in p for w in ("отвор", "слобод", "актив", "работн", "нови ", "достапн")
    ):
        return "navigacija"

    # ВАЖНО: „кој се аплицирал/пријавил" е директор бара ЛИСТА (aplikanti),
    # НЕ е корисник што сака да аплицира.
    if any(w in p for w in (
        "кој се аплицирал", "кои се аплицирале", "кои аплицирале",
        "кој се пријавил", "кои се пријавиле",
    )):
        return "aplikanti_oglas"

    # Дневен/неделен извештај (директор) — ПРЕД apliciraj („апликаци" е подниз)
    if _ima_zbor(p, KLUCNI_DNEVEN_IZVESTAJ) or (
        "извештај" in p
        and any(w in p for w in ("денес", "denes", "недела", "nedela", "термини", "termini"))
    ):
        return "izvestaj_den_nedela"

    # „Аплицирам / пријавувам за работа за X" – пациент аплицира (не текст на оглас)
    if not ima_kreiraj and not _tekst_e_oglas_za_objava(p) and any(w in p for w in (
        "аплицир",
        "сакам да работам", "сакам да се вработам",
        "како да се вработам", "како да аплицирам",
        "сакам да се пријавам за работа",
        "пријавувам за работа", "пријавам за работа",
        "apliciram", "apliciranj",
        "sakam da rabotam", "sakam da se vrabotam",
    )):
        return "apliciraj_za_rabota"
    if not ima_kreiraj and not _tekst_e_oglas_za_objava(p) and any(
        w in p for w in ("апликација", "aplikacija")
    ) and any(w in p for w in ("сакам", "sakam", "како", "kako", "да аплицирам", "da apliciram")):
        return "apliciraj_za_rabota"

    # „Сакам да работам кај вас" / „како да се пријавам" (без позиција) → navigacija
    if not ima_kreiraj and any(w in p for w in (
        "сакам да работам кај вас",
        "како да се пријавам", "како да се пријавиме",
        "sakam da rabotam kaj vas",
    )):
        return "navigacija"

    # „види/покажи/сите/каде/имате/има ли/дали има + оглас" – без зборови за креирање
    pregled_RECI = (
        "сите ", "види ", "видете", "погледни", "погледај", "погледајте",
        "покажи", "прикажи", "однеси", "одведи", "каде се", "каде ",
        "имате", "имате ли", "има ли", "дали има", "има актив",
        "кои се", "кои ", "колку ",
        "листа", "листај", "даj ми", "дај ми", "дади ми",
        "ima li", "dali ima", "pokazi", "prikazi", "vidi", "site ", "ima aktiv",
    )
    ima_glagol_pregled = any(w in p for w in pregled_RECI)
    ima_oglas_zbor = ("оглас" in p or "oglas" in p)
    if ima_oglas_zbor and ima_glagol_pregled and not ima_kreiraj:
        return "navigacija"

    # „активни/отворени/слободни огласи" – директно навигација (без други глаголи)
    # ВАЖНО: исклучи „затвори/затвара" (тоа е друг intent)
    ima_zatvori = any(w in p for w in ("затвори", "затвор", "zatvori", "deaktiviraj"))
    if (
        ima_oglas_zbor
        and any(w in p for w in ("актив", "отвор", "слобод", "нови ", "достапн", "aktiv", "otvor"))
        and not ima_kreiraj
        and not ima_zatvori
    ):
        return "navigacija"

    # Апликанти за оглас (директор) – мора пред kreiraj_oglas
    if _ima_zbor(p, KLUCNI_APLIKANTI):
        return "aplikanti_oglas"

    if _ima_zbor(p, KLUCNI_OGLAS):
        return "kreiraj_oglas"

    # Преглед: „кога е дежурна д-р X" (пред промена)
    if _prasanje_e_pregled_dezurstvo(p):
        return "pregled_dezurstvo"

    if _ima_zbor(p, KLUCNI_OTVORI_ADMIN):
        return "otvori_admin_panel"
    if "администрација" in p and any(
        w in p for w in ("прикажи", "отвори", "однеси", "види", "панел", "prikazi", "otvori")
    ):
        return "otvori_admin_panel"

    # Дежурства: додади / премести (за директор)
    if _ima_zbor(p, KLUCNI_DEZURSTVO):
        return "promeni_dezurstvo"

    # Запиши терапија/дијагноза (лекар) – мора пред zavrshi_pregled
    # (бидејќи zavrshi може и да прима терапија)
    if _ima_zbor(p, KLUCNI_ZAPISHI_TERAPIJA):
        return "zapishi_terapija"

    # ВАЖНО: D1 „заврши преглед" мора пред zakazi/otkazi/prenesi (со „преглед")
    if _ima_zbor(p, KLUCNI_ZAVRSHI):
        return "zavrshi_pregled"

    # Моите прегледи (пациент) – има поспецифични варијанти; мора пред moj_raspored
    if _ima_zbor(p, KLUCNI_MOI_PREGLEDI):
        return "moi_pregledi"

    # B1 „мој распоред" / „закажаните прегледи" - мора пред zakazi_termin
    # ВАЖНО: ова може да биде или лекарски распоред или пациентски преглед –
    # router-от ја решава амбигуитетот според улогата.
    if _ima_zbor(p, KLUCNI_RASPORED):
        return "moj_raspored"

    # Резиме на новости од база — пред навигација („покажи новости" останува navigacija)
    if _ima_zbor(p, KLUCNI_REZIME_NOVOSTI):
        return "novosti_rezime"

    # Листа лекари по специјалност — пред info_lekar („други лекари од оваа специјалност")
    try:
        from ai.opsto.lekari_oddel import prasanje_e_lekari_po_oddel
        from ai.pacient.slobodni_termini import prasanje_e_drugi_lekari_specijalnost

        if prasanje_e_lekari_po_oddel(prasanje):
            return "lekari_oddel"
        if prasanje_e_drugi_lekari_specijalnost(prasanje):
            return "lekari_oddel"
    except ImportError:
        pass

    if _ima_zbor(p, KLUCNI_LEKARI_ODDEL):
        return "lekari_oddel"

    # Област / специјалност на избраниот лекар (не листа „други лекари")
    if any(x in p for x in ("област", "специјалност", "oddel", "oblast", "specijalnost")) and any(
        x in p
        for x in (
            "избран",
            "истиот",
            "погоре",
            "лекарот",
            "д-р",
            " др",
            "докторот",
        )
    ):
        return "info_lekar"

    # Контакт / работно време / локација / услуги — пред info_lekar
    bi = _bolnica_info_intent(p)
    if bi:
        return bi

    # Закажување кај именуван лекар — пред info_lekar („може да ми закажете кај …")
    try:
        from ai.pacient.slobodni_termini import baranje_e_zakazuvanje

        if baranje_e_zakazuvanje(prasanje) and _prasanje_e_konkreten_lekar(prasanje):
            return "zakazi_termin"
    except ImportError:
        pass

    # Конкретен лекар по име — пред навигација („во оваа болница работи др X")
    if _prasanje_e_konkreten_lekar(prasanje) or _ima_kluc_info_lekar(p):
        return "info_lekar"

    # Навигација – пред uslugi
    if _ima_zbor(p, KLUCNI_NAVIGACIJA):
        return "navigacija"

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

    if _ima_zbor(p, KLUCNI_REZULTATI):
        return "rezultati_testovi"

    if _ima_zbor(p, KLUCNI_PREFERENCE):
        return "preference_lekar"

    if _ima_zbor(p, KLUCNI_FAQ_PREGLED):
        return "faq_pregled"

    if _ima_zbor(p, KLUCNI_PREPORAKA):
        return "preporaka_lekar"

    if _ima_zbor(p, KLUCNI_RABOTNO):
        return "rabotno_vreme"

    if _prasanje_e_kontakti(p) or _ima_zbor(p, KLUCNI_KONTAKTI):
        return "kontakti"

    if _ima_zbor(p, KLUCNI_LOKACIJA):
        return "lokacija"

    # „Каде е [оддел]" без контакт → локација
    if any(x in p for x in ("каде е", "каде se", "kade e")) and not _prasanje_e_kontakti(p):
        if any(
            x in p
            for x in (
                "оддел",
                "гинеколог",
                "кардиолог",
                "невролог",
                "уролог",
                "ортопед",
                "лаборатор",
                "радиолог",
                "итна",
                "аптека",
                "спрат",
                "соба",
            )
        ):
            return "lokacija"

    if _ima_zbor(p, KLUCNI_USLUGI):
        return "uslugi"

    # „Каде се лекарите?" → навигација (#lekari), не lekari_oddel
    if any(w in p for w in ("каде се", "каде е", "каде ", "kade se", "kade e")) and any(
        w in p for w in ("лекар", "лекарите", "доктор", "докторите")
    ):
        return "navigacija"

    # „Кои лекари се на X оддел" мора ПРЕД info_lekar
    # (за да не побара име на конкретен лекар, кога всушност прашува за оддел)
    if _ima_zbor(p, KLUCNI_LEKARI_ODDEL):
        return "lekari_oddel"

    # Флексибилно: „лекар/доктор/специјалист" + („оддел/Y") во истиот текст
    if any(w in p for w in ("лекари", "лекарите", "доктори", "докторите")) and any(
        w in p for w in ("оддел", "одделот", "одделение", "специјалност", "од ")
    ) and not any(w in p for w in ("каков", "каква", "како е", "опис")):
        return "lekari_oddel"

    # „Кога е следен работен ден?" — датум/термини, не работно време на болница
    if any(
        w in p
        for w in (
            "следен работен",
            "следниот работен",
            "нареден работен",
            "наредниот работен",
            "прв работен ден",
            "кога е работен ден",
        )
    ):
        return "slobodni_termini"

    try:
        from ai.pacient.slobodni_termini import prasanje_e_ko_e_sloboden_datum_vreme

        if prasanje_e_ko_e_sloboden_datum_vreme(prasanje):
            return "slobodni_termini"
    except ImportError:
        pass

    if _ima_zbor(p, KLUCNI_SLOBODNI):
        return "slobodni_termini"

    return None  # нема jasen keyword match


def detektiraj_intent(prasanje: str) -> str:
    """
    Главна функција - хибриден пристап.

    1. Проба со keyword detector (брзо, бесплатно).
    2. Ако не најде → AI (Groq) за природни варијации.
    3. Ако и AI не успее → "general".
    """
    if not prasanje:
        return "general"

    # Чекор 1: keyword detector со транслитерација
    intent = detektiraj_intent_keyword(prasanje)
    if intent:
        return intent

    # Чекор 2: AI fallback - проба со Groq
    try:
        ai_intent = detektiraj_intent_so_ai(prasanje)
        if ai_intent:
            return ai_intent
    except Exception as e:
        print(f"[intent_detector] AI fallback greska: {e}")

    return "general"
