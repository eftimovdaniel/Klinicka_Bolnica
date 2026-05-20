""" Завршување преглед од лекар - UPDATE status_pregled = 'завршен'. Достапно за СЕКОЈ најавен лекар (не само директор).
Примери:
- „Заврши го прегледот на Петар Иванов"
- „Заврши го утрешниот преглед на Иванов"
- „Заврши преглед ID 42"
- „Заврши го прегледот на Иванов со дијагноза: грип, терапија: парацетамол 3x"
Лекарот може да заврши САМО свои прегледи."""
import re  
from datetime import date  
from database import get_connection  
from ai._kernel.auth import require_lekar  
from ai._kernel.groq_helpers import izvlechi_json_so_ai  
from ai._kernel.prompt_helpers import today_prompt_line  
from ai._kernel.transliteracija import transliterijaj  
from ai._kernel.utils import format_datum_i_vreme  

_RE_TERMIN_ID = re.compile(r"\bID\s*(\d+)\b", re.IGNORECASE | re.UNICODE)  # regex za naogjanje na id brojot vo tekstot
_RE_ZAVRSI_ZATVORI = re.compile(  # regex so koj gi baram klucnite zborovi za zavrshuvanje na pregledot
    r"\b(заврш\w*|zavrsh\w*|затвор\w*|zatvor\w*|затвот\w*|додад\w*|додаj\w*|dodad\w*|dodaj\w*|ажурир\w*|azurir\w*|обнов\w*|обнoви\w*|update)\b",  # razlicni varijanti na zborovite na kirilica i latinica plus update
    re.IGNORECASE | re.UNICODE,  # ignoriranje na mali i golemi bukvi i poddrshka za unikod
)  # kraj na regexot za klucni zborovi za zatvoranje
_RE_DX = re.compile(  # regex za izvlekuvanje na tekstot na dijagnozata od tekstot
    r"(?:дијагноза|dijagnoza)\s*:\s*(.+?)(?=\s+и\s+(?:терапија|terapija)|(?:терапија|terapija)\s*:|$)",  # trazenje na se pomegju klucnite zborovi dx i tx
    re.IGNORECASE | re.UNICODE | re.DOTALL,  # dopustanje na nov red vo tekstot na dijagnozata
)  # kraj na regexot za izvlekuvanje na dijagnoza
_RE_TX = re.compile(  # regex preku koj ja baram propishanata terapija na krajot
    r"(?:терапија|terapija)\s*:\s*(.+)$",  # zemanje na celiot tekst shto preostanuva po zborot terapija
    re.IGNORECASE | re.UNICODE | re.DOTALL,  # vklucuvanje na poddrshka za tekst vo poveke linii
)  # kraj na regexot za terapija
_RE_DX_SO = re.compile(  # regex za slucaevi koga lekarot pishuva so dijagnoza
    r"со\s+дијагноза\s*[:/]?\s*(.+?)(?=\s+и\s+терапија|\s*$)",  # izoliranje na frazata za dijagnoza po zborot so
    re.IGNORECASE | re.UNICODE | re.DOTALL,  # poddrshka za prebaruvanje niz celiot tekst vklucuvajki novi redovi
)  # kraj na regexot za dx so uslov
_RE_TX_SO = re.compile(  # regex za prepoznavanje na terapija vmetnata so vrznici
    r"(?:и\s+)?терапија\s*[:/]?\s*(.+?)\s*$",  # izvlekuvanje na cistiot tekst za terapijata na samiot kraj
    re.IGNORECASE | re.UNICODE | re.DOTALL,  # osiguruvanje deka ke bide faten celiot preostanat string
)  # kraj na regexot za tx so uslov


PROMPT = """
Ти си систем што извлекува податоци за завршување медицински прегледи.
Корисникот е лекар и сака да означи еден или повеќе прегледи како „завршени". Врати САМО JSON:
{"termin_ids": [42, 43] | null, "ime_pacient": "Име Презиме" | null,
 "datum": "YYYY-MM-DD" | null, "site": true | false,
 "dijagnoza": "текст" | null, "terapija": "текст" | null}
Правила:
- ако корисникот спомне „ID 42", „термин 42" → "termin_ids"=[42].
- ако спомне повеќе ID (пр. „1, 2, 3" или „42 и 43") → "termin_ids"=[1,2,3].
- ако спомне „сите", „сите мои", „сите денешни" → "site"=true.
- ако спомне име на пациент → "ime_pacient"=име+презиме.
- датум: „денес"=денешен, „утре"=денес+1, „вчера"=денес-1, „понеделник"... = најблиски тој ден.
- ако корисникот спомне „дијагноза: X" или „dx: X" → "dijagnoza"=X.
- ако корисникот спомне „терапија: Y" или „tx: Y" → "terapija"=Y.
- ако нема ништо јасно → сите вредности null/false.
БЕЗ markdown, БЕЗ објаснувања. Само JSON. """.strip()  # tekstot na sistemskiot prompt iscisten od prazni mesta na pocetokot i krajot

# funkcija za proverka dali baranjeto e za zatvoranje pregled
def prasanje_e_zavrshi_pregled(prasanje: str) -> bool:  
    if not prasanje or not prasanje.strip():  # proverka dali vnesenoto prasanje e prazno
        return False  # vrakjam false ako nema nikakov tekst vo prasanjeto
    p = transliterijaj(prasanje).lower()  # go prefrlam celiot tekst vo latinica i mali bukvi za polesna obrabotka
    ima_akcija = bool(_RE_ZAVRSI_ZATVORI.search(p))  # proveruvam dali postoi zborot zavrsi ili zatvori nekade
    ima_termin = bool(  # proverka dali vo prasanjeto e spomnat termin ili pregled
        re.search(r"\b(преглед|pregled|термин|termin)\b", p, re.UNICODE)  # prebaruvanje na zborovite na dvete pisma
    )  # kraj na unkod proverkata za zborot termin
    ima_dx_tx = bool(  # proveruvam dali se spomnati zborovite za terapija i dijagnoza
        re.search(r"\b(дијагноз|dijagnoz|терап|terap)\b", p, re.UNICODE)  # prebaruvanje niz korenite na zborovite
    )  # kraj na proverkata za prisustvo na medicinski izrazi
    if ima_akcija and ima_termin:  # ako gi ima i akcijata i zborot termin vo istoto prasanje
        return True  # potvrduvam deka se raboti za zatvoranje na termin
    if ima_akcija and re.search(  # dopolnitelna proverka za akcija nasocena kon nekoe lice
        r"\bна\s+[a-zа-я]", p, re.UNICODE  # baranje na konstrukcijata na plus nekoe ime
    ):  # kraj na uslovot so predlogot na
        return True  # vrakjam true bidejki lici na akcija vrz pacient
    if _RE_DX.search(prasanje) and _RE_TX.search(prasanje):  # ako ima direktno vneseno i dijagnoza i terapija
        return True  # ova znaci deka lekarot saka direktno da go zavrsi pregledot so vnos
    if ima_akcija and (_RE_DX.search(prasanje) or _RE_DX_SO.search(prasanje)):  # akcija sklopena so detektirana dijagnoza
        return True  # potvrduvam deka ova e validno baranje za update
    if ima_akcija and ima_dx_tx:  # ako ima bilo kakva akcija vrzana so medicinski koren na zbor
        return True  # ja odobruvam validnosta na namerata
    return False  # vrakjam false bidejki nieden od uslovite za prepoznavanje ne pominal


# funkcija za generiranje varijanti na imeto zaradi like operatorot
def _like_variants_ime(word: str) -> list[str]:  
    """Latinica + kirilica za prebaruvanje vo ime_pacient."""
    w = (word or "").strip().lower()  # go transformiram zborot vo mali bukvi i brisham prazni mesta
    if len(w) < 2:  # ako zborot e prekratok odnosno ima pomalku od dva karakteri
        return []  # vrakjam prazna lista bidejki ne e bezbedno za lajk
    out: set[str] = {w}  # pravam set i ja dodavam originalnata varijanta na zborot
    cyr = transliterijaj(word).strip().lower()  # pravam transliteracija vo kirilicna odnosno latinicna forma
    if cyr and cyr != w:  # ako preprevodot e uspeshen i e razlicen od pocetniot zbor
        out.add(cyr)  # ja dodavam i taa nova tekstualna varijanta vo setot
    return list(out)  # go vrakjam setot konvertiran vo obicna lista od stringovi


def _sql_filter_ime_pacient(ime_pacient: str) -> tuple[str, list]:  # funkcija za kreiranje dinamicki sql filter za pretraga po ime
    delovi = [d for d in ime_pacient.strip().split() if len(d) >= 2]  # go delam imeto na zborovi i gi otstranuvam prekratskite
    if not delovi:  # ako nema nitu eden validen del po delenjeto na stringot
        return "", []  # vrakjam prazen uslov i prazna lista na parametri
    if len(delovi) == 1:  # scenario koga imame vneseno samo eden zbor ako ime
        vars_ = _like_variants_ime(delovi[0])  # gi zeman site jazicni varijanti za toj zbor
        if not vars_:  # ako ne se generirale validni tekstualni varijanti
            return "", []  # prekinuvam i vrakjam prazni vrednosti
        clause = " AND (" + " OR ".join(["LOWER(ime_pacient) LIKE %s"] * len(vars_)) + ")"  # sozdavam sql or uslov za sekoja varijanta
        return clause, [f"%{v}%" for v in vars_]  # gi pakuvam vrednostite so procenti za sql lajk prebaruvajneto

    first, last = delovi[0], delovi[-1]  # gi zemam prviot i posledniot zbor od stringot kako ime i prezime
    v_first = _like_variants_ime(first)  # generiram jazicni varijanti za prvoto ime
    v_last = _like_variants_ime(last)  # generiram jazicni varijanti za prezimeto

# funkcija za povrzuvanje na parovi zborovi so and uslov
    def _and_pair(va: list[str], vb: list[str]) -> tuple[str, list]:  
        p: list = []  # lokalna lista za sql parametrite
        parts: list[str] = []  # lokalna lista za delovite od sql upitot
        for a in va:  # ciklus niz site varijanti na prviot zbor
            parts.append("LOWER(ime_pacient) LIKE %s")  # dodavam sql klauzula za prviot zbor
            p.append(f"%{a}%")  # go pakuvam parametarot so procent od strana
        for b in vb:  # ciklus niz site varijanti na vtoriot zbor
            parts.append("LOWER(ime_pacient) LIKE %s")  # dodavam sql klauzula za vtoriot zbor
            p.append(f"%{b}%")  # go pakuvam vtoriot parametar za sql lajk upitot
        return "(" + " AND ".join(parts) + ")", p  # gi spojuvam delovite so and operator vnatre vo zagradite

    fwd, p_fwd = _and_pair(v_first, v_last)  # generiram sql par za redosled ime pa prezime
    rev, p_rev = _and_pair(v_last, v_first)  # generiram sql par za obraten redosled prezime pa ime
    return " AND (" + fwd + " OR " + rev + ")", p_fwd + p_rev  # gi spojuvam dvata redosledi so glaven or uslov za bazata

 #funkcija koja go vrakja sql uslovot za proverka na statusot
def _status_zakazan_sql() -> str:  
    return (  # vrakjanje na stringot na sql klauzulata
        "COALESCE(NULLIF(TRIM(status_pregled), ''), 'закажан') = 'закажан'"  # se spravuvam so prazni poli i pretvoram vo zakazan
    )  # kraj na sql klauzulata za statusot

# funkcija za naogjanje na id direktno od tekstot so regex
def _termin_id_od_prasanje(prasanje: str) -> int | None:  
    m = _RE_TERMIN_ID.search(prasanje or "")  # go baram shablonot za id niz tekstot
    if not m:  # ako ne e pronajden nikakov vnatreshen matches
        return None  # vrakjam none bidejki nema id broj vo tekstot
    try:  # zapocnuvam bidejki konverzijata moze da potfrli
        return int(m.group(1))  # go pretvoram grupniot regex naod vo cel broj i go vrakjam
    except (TypeError, ValueError):  # spravuvanje so greshki pri nevalidna konverzija na brojot
        return None  # vrakjam none ako imalo problem pri pretvoranjeto

# funkcija za zemanje na id broevi od memorijata na razgovorot
def _termin_ids_od_kontekst(kontekst: dict | None) -> list[int]: 
    if not isinstance(kontekst, dict):  # proverka dali kontekstot e validen rechnik
        return []  # vrakjam prazna lista ako ne postoi rechnikot
    raw = kontekst.get("last_raspored_termin_ids")  # go baram klucot za posledni prikazani id broevi od rasporedot
    if not isinstance(raw, list):  # proveruvam dali zemenata vrednost e naistina lista
        return []  # vrakjam prazno bidejki nema struktura na lista vnatre
    ids: list[int] = []  # inicijaliziram nova prazna lista za cistite celi broevi
    for x in raw:  # ciklus niz sekoj element od sirovata lista
        try:  # obid za bezbedna konverzija na sekoj element poedinecno
            ids.append(int(x))  # go dodavam uspesno konvertiraniot broj vo listata ids
        except (TypeError, ValueError):  # preskoknuvam ako elementot ne e brojka
            continue  # prodolzuvam so sledniot element od ciklusot
    return ids  # ja vrakjam strukturiranata lista so celi broevi na terminite


def _izvlechi(prasanje: str) -> dict:  # funkcija za povik na ai modelot i izvlekuvanje json struktura
    from ai._kernel.groq_helpers import groq_zadolzhitelen  # uvoz na proverkata za aktivna vrska so groq api

    if msg := groq_zadolzhitelen():  # ako se javi poraka za greshka vo vrskata so servisot
        return {"_error": msg}  # ja vrakjam taa poraka kako greshka vo rechnikot

    full = f'{today_prompt_line()}\n\nПрашање: "{prasanje}"\nВрати JSON.'  # go spremam finalniot prompt za modelot so se tekovniot den
    podatoci = izvlechi_json_so_ai(full, PROMPT, log_tag="zavrshi_pregled")  # povik do pomosnata funkcija i zemanje strukturiran json response
    if podatoci.get("_error"):  # ako ima greshka uste pri samiot povik na ai modelot
        return podatoci  # go vrakjam rechnikot so greshka vednas nazad
    tid = _termin_id_od_prasanje(prasanje)  # proveruvam dali jas mozam da najdam id preku regex za sekoj slucaj
    if tid is not None and not podatoci.get("termin_ids"):  # ako jas najdov id a modelot go propushtil vo jsonot
        podatoci["termin_ids"] = [tid]  # racno go vmetnuvam id brojot vo strukturata so podatoci
    from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje  # uvoz na logikata za vadenje datum od tekst

    d = datum_za_pregledi_od_prasanje(prasanje)  # ja povikuvam funkcijata da prepoznae tekstualni datumi ako denes ili utre
    if d and not podatoci.get("datum"):  # ako e pronajden datum a modelot nema nisto staveno vo jsonot
        podatoci["datum"] = d.isoformat()  # go zacuvasam vo standardiziran izo format na string
    return podatoci  # go vrakjam celosno spremniot i korigiran rechnik so podatoci


def _najdi_termin(  # funkcija za prebaruvanje na termini vo mysql bazata po poveke kriteriumi
    doctor_id: int,  # id na lekarot koj ja vrshi operacijata
    termin_id: int | None,  # opciono id na specificen termin
    ime_pacient: str | None,  # opciono ime na pacientot za pretraga
    datum_str: str | None,  # opcionen datum na pregleduvanje
    *,  # granica za poedinecni imenuvani argumenti vo python
    samo_zakazani: bool = True,  # flag dali da prebaruvame samo seuste nezavrsheni pregledi
) -> list[dict]:  # vrakja lista od rechnici so pronajdenite termini
    """Termini na lekarot — po ID, ime (lat/kir) ili datum."""
    conn = get_connection()  # vospostavuvam aktivna konekcija so mysql bazata na podatoci
    cur = conn.cursor(dictionary=True)  # kreiram kursor koj vrakja redovi ako python rechnici

    if termin_id:  # ako eksplicitno e podadeno id na terminot preku argument
        cur.execute(  # go izvrshuvam upitot za selektiranje po id i id na doktorot
            "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"  # gi baram samo neophodnite polinja
            " FROM Termin_pregled WHERE termin_ID = %s AND doctor_ID = %s",  # uslov za tochen termin i sopstvenost na lekarot
            (termin_id, doctor_id),  # torka na parametri za predotvranje od sql injekcii
        )  # kraj na egzekucijata na selektot po id
        rows = cur.fetchall()  # gi prevzemam site redovi shto gi vratila bazata
        cur.close()  # vednas go zatvoram kursorot za da oslobodam memorija
        conn.close()  # ja zatvoram vrskata so mysql bazata
        return rows  # gi vrakjam pronajdenite podatoci od bazata na podatoci

    sql = (  # pocnuvam da go gradam dinamickiot sql upit za ostanatite slucaevi
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"  # selekcija na osnovnite polinja
        " FROM Termin_pregled WHERE doctor_ID = %s"  # poceten uslov deka terminot mora da e kaj ovoj lekar
    )  # kraj na pocetniot string na upitot
    params: list = [doctor_id]  # ja inicijaliziram listata na parametri so id na lekarot

    if samo_zakazani:  # ako e aktiviran uslovot za baranje samo na zakazani termini
        sql += f" AND {_status_zakazan_sql()}"  # ja lepam prethodno definiranata status klauzula vo stringot

    if datum_str:  # ako vo filtrite e prosleden konkreten datum ako uslov
        sql += " AND datum_pregled = %s"  # go dodavam sql uslovot za sovpagjanje na datumot
        params.append(datum_str)  # ja stavam vrednosta na datumot vo listata so parametri

    if ime_pacient:  # ako e vneseno ime na pacient za prebaruvanje vo bazata
        clause, clause_params = _sql_filter_ime_pacient(ime_pacient)  # gi zemam dinamickite sql delovi od filterot za ime
        if clause:  # ako filterot generiral validna sql klauzula
            sql += clause  # go spojuvam generiraniot tekst so glavniот sql uslov
            params.extend(clause_params)  # gi dodavam site novi parametri vo glavnata lista
        if "@" in ime_pacient:  # ako imeto sodrzi majmunche shto ukazuva na prebaruvanje po email adresa
            sql += " AND LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))"  # dodavam bezbeden uslov za filtriranje po email
            params.append(ime_pacient.strip())  # go chistam emailot od prazni mesta i go stavam vo parametrite

    sql += " ORDER BY datum_pregled, vreme_pregled"  # gi sortiram rezultatite po hronoloshki redosled na pregledite
    cur.execute(sql, params)  # go izvrshuvam finalno sklopeniot i bezbeden dinamicki sql upit
    rows = cur.fetchall()  # gi povlekuvam site pronajdeni redovi od bazata vo promenlivata rows
    cur.close()  # go zatvoram aktivniot kursor po izvrshuvanjeto
    conn.close()  # ja zatvoram konekcijata do bazata na podatoci
    return rows  # ja vrakjam listata so pronajdeni termini nazad


def _poraka_ne_najden_termin(doctor_id: int, ime: str | None) -> str:  # pomoshna funkcija za generiranje ubava poraka pri neuspeh
    """Pomoshna poraka — slicni iminja ili pogreshen status."""
    base = "Не најдов соодветен закажан преглед кај тебе."  # definiram osnoven tekst za porakata za greshka
    if not ime:  # ako ne bilo preneseno ime na pacient ako kriterium
        return (  # vrakjam nasoka kako korisnikot da postapi vo ovoj slucaj
            base  # osnovnata poraka
            + '\n\nПровери "Мој распоред" или наведи "Заврши термин ID …".'  # sovet za vnesuvanje na konkreten id broj
        )  # kraj na stringot za vrakjanje koga nema ime

    site = _najdi_termin(doctor_id, None, ime, None, samo_zakazani=False)  # pravam ushte edna prebaruvanje bez filter za status
    if not site:  # ako voopshto ne postoi termin so toa ime kaj ovoj lekar vo celata baza
        return (  # vrakjam detalno izvestuvanie za nepostoenje na takov pacient vo negoviot karton
            base  # pocetniot tekst
            + f'\n\nНемам термин за "{ime}" на твојот распоред.\n'  # specificiram za koe ime stanuva zbor
            'Провери правопис (латиница/кирилица) или ID од "Мој распоред".'  # sovet za proverka na bukvite od tastaturata
        )  # kraj na stringot koga nema nikakov termin so toa ime

    zakazani = [  # filtriram lokalno koi od pronajdenite termini se vo status zakazan
        r  # go zacuvuvam redcheto
        for r in site  # vrtam niz site rezultati vrateni od bazata
        if (r.get("status_pregled") or "закажан").strip() == "закажан"  # uslov za filtriranje na samo zakazanite polinja
    ]  # kraj na listickata kompresija
    if zakazani:  # ako imalo zakazani termini no ne se sovpadnal datumot
        return base  # ja vrakjam samo osnovnata poraka za nesovpagjanje

    linii = [  # pocnuvam da gradam detalna lista na linii za korisnikot koga terminite se so drug status
        base,  # ja stavam pocetnata linija vo listata
        "",  # prazen red za poubav estetski izgled na porakata
        f'Имам преглед за "{ime}", но не е со статус „закажан":',  # objasnuvanje deka terminot e najden no ima razlicen status
    ]  # kraj na pocetnata inicijalizacija na liniite
    for r in site[:5]:  # prikazuvam najmnogu do pet termini za da ne go preplavam ekranom so tekst
        st = (r.get("status_pregled") or "—").strip()  # go zemam statusot i mu pravam chistenje na stringot od prazni mesta
        linii.append(  # dodavam nov red so detali za sekoj pronajden termin poedinecno
            f"• ID {r['termin_ID']}: {r['ime_pacient']} — "  # prikazuvam id broj i ime na pacient
            f"{format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])} (статус: {st})"  # prikazuvam koga bil pregledot i koj e statusot
        )  # kraj na linijata za tekovniot pregled od ciklusot
    linii.append(  # dodavam zavrshen sovet na krajot od porakata za korisnikot
        "\nАко сакате да го ажурирате, наведете ID или контактирајте админ."  # nasoka za reshavanje na problemot so status
    )  # kraj na poslednata linija
    return "\n".join(linii)  # gi spojuvam site linii vo eden ubav tekst razdelen so novi redovi


def _prazna_dx_tx(v: str | None) -> bool:  # funkcija koja proveruva dali vrednostite za dijagnoza ili terapija se prazni
    if v is None:  # ako vrednosta e nane odnosno voopshto ne e ispratena od modelot
        return True  # vrakjam tru bidejki toa se smeta za prazno pole
    t = str(v).strip()  # ja pretvoram vrednosta vo klasicen string i gi brisham okolnite prazni mesta
    return not t or t in ("/", "—", "-", "…", ".", "n/a", "N/A", "нема", "none")  # vrakjam tru ako stringot e kratok ili sodrzi znaci za prazno pole


def _zavrshi(termin_id: int, dijagnoza: str | None, terapija: str | None) -> None:  # moja funkcija shto go pravi realniот apdejt vo bazata
    """Markira pregled kako zavrshen. Opciono zapishuva dx/tx."""
    conn = get_connection()  # otvoram nova chista konekcija do mysql bazata na podatoci
    cur = conn.cursor()  # kreiram klasicen kursor za izvleshuvanje na izmenite
    sets = ["status_pregled = 'завршен'"]  # ja definiram pocetnata izmena kade statusot se postavuva vo zavrshen
    params: list = []  # kreiram prazna lista kade ke gi chuvam vrednostite na parametrite za apdejtot
    if dijagnoza and not _prazna_dx_tx(dijagnoza):  # ako ima vneseno dijagnoza i taa ne e prazen znak
        sets.append("dijagnoza = %s")  # go dodavam poleto za dijagnoza vo set delot na sql izrazot
        params.append(dijagnoza)  # ja stavam vrednosta na dijagnozata vo listata so parametri
    if terapija and not _prazna_dx_tx(terapija):  # ako ima pronajdeno tekst za terapija i ne e prazen simbol
        sets.append("terapija = %s")  # go dodavam poleto za terapija vo kupot za izmena
        params.append(terapija)  # ja prikachuvam vrednosta vo listata za izvleshuvanje
    params.append(termin_id)  # go stavam id brojot na terminot na samiot kraj ako posleden parametar za kade uslovot
    cur.execute(  # ja povikuvam funkcijata za izvleshuvanje na podgotveniot sql apdejt upit
        f"UPDATE Termin_pregled SET {', '.join(sets)} WHERE termin_ID = %s",  # dinamicki gi spojuvam polinjata za azuriranje so zapirki
        params,  # ja prenesuvam zashtitenata lista so parametri
    )  # kraj na izvleshuvanjeto na apdejtot vo bazata
    conn.commit()  # gi potvrduvam i trajno gi zacuvuvam nastanatite izmeni vo mysql bazata
    cur.close()  # go zatvoram kursorot po uspesnoto snimanje
    conn.close()  # ja zatvoram konekcijata za da go oslobodam konekcikiot pul


def _azuriraj_dx_tx(termin_id: int, dijagnoza: str | None, terapija: str | None) -> bool:  # funkcija za partialen apdejt na medicinski beleshki bez izmena na statusot
    """UPDATE dx/tx БЕЗ менување на статусот (за пр. ажурирање на веќе завршен преглед)."""
    sets: list[str] = []  # lokalna lista vo koja ke gi sobiram delovite od set delot na sql upitot
    params: list = []  # parallel lista vo koja ke gi chuvam vrednostite za sekoja sql klauzula
    if dijagnoza and not _prazna_dx_tx(dijagnoza):  # ako ima validna dijagnoza koja ne e prazen simbol kako kosi crti
        sets.append("dijagnoza = %s")  # go dodavam delot za dijagnoza vo gradeniot sql upit
        params.append(dijagnoza)  # ja prikachuvam realnata vrednost na dijagnozata vo parametrite
    if terapija and not _prazna_dx_tx(terapija):  # ako lekarot pripishal validna terapija a ne samo prazen znak
        sets.append("terapija = %s")  # go dopolnuvam upitot so polenoto za propishanata terapija
        params.append(terapija)  # ja stavam vrednosta na terapijata vo listata so sql parametri
    if not sets:  # ako po site proverki ne se sobrala nikakva validna izmena za zacuvuvanje
        return False  # vrakjam false bidejki nema sto da apdejtiram vo bazata
    params.append(termin_id)  # go dodavam id brojot na terminot kako posleden parametar za where uslovot
    conn = get_connection()  # otvoram nova konekcija kon mysql bazata na podatoci
    cur = conn.cursor()  # kreiram klasichen kursor za izvrshuvanje na izmenata
    cur.execute(  # ja izvrshuvam dinamichki sklopena update naredba so site zashtiteni parametri
        f"UPDATE Termin_pregled SET {', '.join(sets)} WHERE termin_ID = %s",  # gi spojuvam delovite od set delot so zapirka megju niv
        params,  # bezbedno ja prenesuvam listata so vrednosti kako tupla parametri
    )  # kraj na izvrshuvanjeto na konkretniot update upit
    conn.commit()  # gi potvrduvam i trajno gi snimam izmenite vo postojnata baza
    cur.close()  # go zatvoram aktivniot kursor za da oslobodam memorija od mysql konektorot
    conn.close()  # ja zatvoram vrskata so mysql serverot za da oslobodam konekciski resurs
    return True  # vrakjam true kako potvrda deka apdejtot e uspeshno izvrshen vo bazata


def _najdi_site_zakazani(doctor_id: int, datum_str: str | None) -> list[dict]:  # funkcija za povlekuvanje na apsolutno site zakazani termini odednas
    """Site zakazani pregledi na lekarot (opciono filtrirani po datum)."""
    conn = get_connection()  # otvoram aktivna vrska do mysql databazata
    cur = conn.cursor(dictionary=True)  # koristam recnicki kursor za polesna obrabotka na polinjata vo kod
    sql = (  # go pishuvam osnovniot sql select tekst za povlekuvanje na terminite
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"  # selektiram samo id ime datum vreme i status
        f" FROM Termin_pregled WHERE doctor_ID = %s AND {_status_zakazan_sql()}"  # filtriram po sopstvenik lekar i aktiven status
    )  # kraj na definiranjeto na pocetniot sql string
    params: list = [doctor_id]  # ja inicijaliziram mapata od parametri so id brojot na doktorot od najavata
    if datum_str:  # ako dopolnitelno e pobarano filtriranje na site termini za konkreten den
        sql += " AND datum_pregled = %s"  # go lepam sql uslovot za filtriranje po datum na pregledot
        params.append(datum_str)  # go stavam datumot vo kupot so parametri za izvleshuvanje
    sql += " ORDER BY datum_pregled, vreme_pregled"  # gi sortiram site pronajdeni termini po raspored na chasovi
    cur.execute(sql, params)  # go izvrshuvam finalniot select upit vo bazata
    rows = cur.fetchall()  # gi sobiram site redovi so termini shto se pronajdeni vo bazata
    cur.close()  # go zatvoram kursorot za da ne protekuva memorija vo aplikacijata
    conn.close()  # ja zatvoram vrskata so mysql serverot
    return rows  # ja vrakjam listata so site pronajdeni zakazani termini kaj doktorot


def _zavrshi_mnogu(rows: list[dict], dijagnoza: str | None, terapija: str | None) -> str:  # funkcija za masovno zatvoranje na poveke termini vo serija
    """Zavrshi poveke pregledi i vrati rezime."""
    if not rows:  # ako listata so termini e prazna odnosno nema nisto za obrabotka
        return "Нема закажани прегледи за завршување."  # vednas vrakjam izvestuvanje do lekarot vo asistentot

    uspesni = 0  # brojac za uspesno zatvoreni termini vo bazata
    preskoknati = 0  # brojac za termini koi bile preskoknati poradi nesoodveten status
    for r in rows:  # zapocnuvam ciklus niz sekoj poedinecen termin od listata
        if r["status_pregled"] != "закажан":  # ako terminot vo megjuvreme go smenil statusot i ne e zakazan
            preskoknati += 1  # go zgolemuvam brojacot na preskoknati elementi za eden
            continue  # vednas preodjam na obrabotka na sledniot termin od ciklusot
        _zavrshi(r["termin_ID"], dijagnoza, terapija)  # ja povikuvam glavnata funkcija za izmena za tekovniot id broj
        uspesni += 1  # go zgolemuvam brojacot na uspesni zatvoranja za eden po transakcijata

    linii = [f"Завршени {uspesni} прегледи."]  # ja kreiram pocetnata linija na izveshtajot so brojot na uspesni izmeni
    if preskoknati:  # ako vo tekot na ciklusot imalo preskoknati termini koi veke bile zatvoreni
        linii.append(f'Прескокнати {preskoknati} (веќе немаа статус „закажан").')  # dodavam informativna linija za preskoknatite vo izveshtajot

    linii.append("")  # stavam eden prazen element vo listata za vizuelno odvojuvanje na sekciite vo izlezot
    linii.append("Детали:")  # dodavam naslov za delot kade shto ke bidat izlistani pregledite so detali
    for r in rows:  # ushte eden ciklus niz listata na termini za podgotovka na detalniot prikaz
        if r["status_pregled"] != "закажан":  # ako terminot ne bil del od grupata na uspesno izmeneti
            continue  # go preskoknuvam i ne go prikazuvam vo finalniot izveshtaj za korisnikot
        linii.append(  # dodavam detalen red vo tekstualniot izveshtaj za sekoj zatvoren pregled
            f"• ID {r['termin_ID']}: {r['ime_pacient']} ({format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])})"  # prikazuvam id ime i tochen chas
        )  # kraj na dodavanjeto na redot od ciklusot vo izveshtajot
    return "\n".join(linii)  # gi spojuvam site podgotveni linii vo eden finalen izveshtaj so novi redovi


def odgovori_za_zavrshi(  # mojata glavna hendler funkcija koja ja povikuva ruterot na asistentot
    prasanje: str, lekar: dict | None, kontekst: dict | None = None  # prima prasanje podatoci za lekarot i kontekst od razgovorot
) -> str:  # sekogash vrakja string poraka koja se prikazuva na interfejsot kaj lekarot
    """Glavna tocka - povikana od router-ot."""
    if err := require_lekar(lekar):  # pravam prvichna proverka dali korisnikot voopshto ima uloga na lekar vo sistemot
        return err  # ja vrakjam sistemskata poraka za greshka ako korisnikot ne e avtoriziran lekar

    doctor_id = lekar["doctor_ID"]  # go zemam i zacuvuvam id brojot na lekarot od negovata aktivna sesija

    termin_ids: list[int] = []  # definiram pocetna prazna lista vo koja ke gi chuvam id broevite na terminite
    tid = _termin_id_od_prasanje(prasanje)  # se obiduvam brzo da izvlecham id broj od prasanjeto preku mojot regularen izraz
    if tid is not None:  # ako mojot regularen izraz uspesno pronashel tochen id broj vo prasanjeto
        termin_ids = [tid]  # go stavam toj pronajden broj kako edinstven element vo listata za obrabotka

    # BUG FIX: brz tek bez AI ako veke imame ID + dx/tx (ili gi nema)
    # mozhe da se izvlechat regex-no. Sprechuva 429 da go blokira korisnikot.
    dx_match = _RE_DX.search(prasanje)
    dx_so_match = _RE_DX_SO.search(prasanje)
    tx_match = _RE_TX.search(prasanje)
    dijagnoza_regex = (
        (dx_match.group(1).strip() if dx_match else None)
        or (dx_so_match.group(1).strip() if dx_so_match else None)
    )
    terapija_regex = tx_match.group(1).strip() if tx_match else None

    # Proverka dali prasanjeto voopshto mentionira dx/tx kluc
    _p_low_check = prasanje.lower()
    ima_kluc_dx = "дијагноз" in _p_low_check or "dijagnoz" in _p_low_check
    ima_kluc_tx = "терапиј" in _p_low_check or "terapij" in _p_low_check

    # Ako imame ID i ne ni treba AI - prejdi vo brz tek
    skip_ai = bool(termin_ids) and bool(
        # Ako voopshto ne se spomenati dx/tx vo prasanjeto
        (not ima_kluc_dx and not ima_kluc_tx)
        # Ili gi imame i dvete od regex
        or (
            (not ima_kluc_dx or dijagnoza_regex)
            and (not ima_kluc_tx or terapija_regex)
        )
    )

    if skip_ai:
        podatoci = {
            "termin_ids": termin_ids,
            "dijagnoza": dijagnoza_regex,
            "terapija": terapija_regex,
            "ime_pacient": None,
            "datum": None,
            "site": False,
        }
    else:
        podatoci = _izvlechi(prasanje)  # ja povikuvam funkcijata za kompletna analiza na prasanjeto so pomosh na ai modelot
        if podatoci.get("_error"):  # ako pri analizata ili komunikacijata so ai modelot se pojavila nekakva greshka
            # FALLBACK: ako imame ID iako AI ne raboti - prodolzi so toa shto go imame
            if termin_ids:
                podatoci = {
                    "termin_ids": termin_ids,
                    "dijagnoza": dijagnoza_regex,
                    "terapija": terapija_regex,
                    "ime_pacient": None,
                    "datum": None,
                    "site": False,
                }
            else:
                return str(podatoci["_error"])  # vednas ja vrakjam porakata za greshka kako odgovor na interfejsot

    dijagnoza = (podatoci.get("dijagnoza") or "").strip() or None  # ja zemam izvlecenata dijagnoza ja chistam i ja postavuvam na nane ako e prazna
    terapija = (podatoci.get("terapija") or "").strip() or None  # go zemam tekstot za terapijata i go formatiram bez prazni mesta na kraevite

    if termin_ids and (_prazna_dx_tx(dijagnoza) or _prazna_dx_tx(terapija)):  # ako doktorot navedel konkreten id no propushtil dijagnoza ili terapija
        parts = []  # kreiram lokalna lista vo koja ke gi stavam iminjata na polinjata shto nedostigaat vo vnesot
        if _prazna_dx_tx(dijagnoza):  # proveruvam dali specificno nedostiga vrednost za poleto dijagnoza
            parts.append("дијагноза")  # go dodavam zborot dijagnoza vo listata so polinja shto falat
        if _prazna_dx_tx(terapija):  # proveruvam dali lekarot zaboravil da napishe soodvetna terapija pri zatvoranjeto
            parts.append("терапија")  # go dodavam zborot terapija vo kupot so polinja za izvestuvanje
        return (  # vrakjam poraka so nasoki deka zatvoranje na konkreten id bara zadolzitelni medicinski podatoci
            "За да го завршам прегледот, наведете вистинска "  # poceten tekst na porakata za predupreduvanje
            + " и ".join(parts)  # gi spojuvam polinjata shto falat so zborot i za popriroden jazichen izgled
            + ' (не само "/" или празно). Пример:\n'  # napomena deka ne se dozvoleni samo simboli kako kosi crti
            '"Затвори го прегледот со Дијагноза: Мигрена, и терапија: Аналгетик".'  # davam tochen primer kako treba da izgleda komandata
        )  # kraj na stringot za predupreduvanje pri prazni medicinski podatoci

    if not termin_ids:  # ako mojot brz regularen izraz prethodno ne uspel da izvleche id broj od tekstot
        ai_ids = podatoci.get("termin_ids") or []  # gi zemam id broevite koi gi izvlekol ai modelot preku json strukturiranjeto
        if isinstance(ai_ids, int):  # ako ai modelot vratil samo eden broj namesto cela lista vo json rezultatot
            ai_ids = [ai_ids]  # go pakuvam toj poedinecen broj vo klasicna python lista so eden element
        try:  # blok za bezbedno pretvoranje na site elementi vrateni od ai modelot vo chisti celi broevi
            termin_ids = [int(x) for x in ai_ids if x is not None]  # pravam listicka kompresija i filtriram nane vrednosti vo procesot
        except (TypeError, ValueError):  # ako nekoj od elementite vo listata ne mozel da se konvertira vo brojka
            termin_ids = []  # ja resetiram listata na prazna poradi nebezbedni ili korumpirani podatoci od modelot

    if not termin_ids:  # ako se ushte nemame pronajdeno id broevi nitu od prasanjeto nitu od json odgovorot na ai
        ctx_ids = _termin_ids_od_kontekst(kontekst)  # se obiduvam da gi povlecham id broevite od aktivniot kontekst na prethodnite poraki
        if len(ctx_ids) == 1:  # ako vo kontekstot na prethodnata poraka imalo prikazano tocno eden edinstven termin
            termin_ids = ctx_ids  # pretpostavuvam deka lekarot se odnesuva na toj termin i go zacuvuvam vo listata

    ime = (podatoci.get("ime_pacient") or "").strip()  # go zemam imeto na pacientot od izvlecenite podatoci i go chistam od prazni mesta
    datum_str = podatoci.get("datum")  # go zacuvuvam datumot dokolku ai modelot uspel da go identificira vo tekstot
    site = bool(podatoci.get("site"))  # go pretvoram flagot za masovna akcija vrz site termini vo klasicna bulova vrednost

    # SLUCAJ 1: "site" / "site deneshni"
    if site:  # ako lekarot eksplicitno pobaral da se zatvorat site negovi termini odednas vo porakata
        rows = _najdi_site_zakazani(doctor_id, datum_str)  # gi baram site aktivni zakazani termini kaj nego filtrirani po datum
        if not rows:  # ako bazata ne vratila nitu eden termin so status zakazan za tie kriteriumi
            kade = " za toj datum" if datum_str else ""  # podgotvuvam tekst koj ke go pojasni datumot vo porakata dokolku go ima
            return f"Немаш закажани прегледи{kade}."  # vrakjam chista poraka deka nema pronajdeno termini za masovna akcija
        return _zavrshi_mnogu(rows, dijagnoza, terapija)  # ja povikuvam funkcijata za serisko zatvoranje i go vrakjam nejziniot rezultat

    # SLUCAJ 2: lista na konkretni ID-a
    if termin_ids:  # ako ima ime sobrano eden ili poveke konkretni id broevi za zatvoranje vo listata
        rows = []  # kreiram prazna lista kade ke gi soberam potvrdenite redovi od bazata za tie broevi
        nepostoekji: list[int] = []  # lista vo koja ke gi chuvam broevite koi ne pripagaat na ovoj lekar ili voopshto ne postojat
        for tid in termin_ids:  # vrtam vo ciklus niz sekoj poedinecen id broj vnesen od lekarot vo baranjeto
            r = _najdi_termin(doctor_id, tid, None, None)  # pravam brza selekcija od bazata po sopstvenik lekar i tochen id broj
            if r:  # ako terminot so toa konkretno id postoi i navistina e kaj ovoj lekar na raspored
                rows.extend(r)  # gi dodavam pronajdenite podatoci za toj pregled vo glavnata sobirna lista
            else:  # ako terminot ne e pronajden ili e kaj drug kolega lekar vo bolnicata
                nepostoekji.append(tid)  # go stavam toj nevaliden broj vo kupot za prijavuvanje na greshki na krajot

        if not rows:  # ako po celata proverka niz bazata ne uspeavme da potvrdime nitu eden edinstven termin za ovoj lekar
            return f"Не најдов твои термини со ID: {', '.join(str(x) for x in nepostoekji)}."  # vrakjam izvestuvanje so site utnati broevi

        # ako samo eden - daj obicen format
        if len(rows) == 1:  # ako vo listata na potvrdeni termini za izmena ima tocno eden pregled
            t = rows[0]  # go izoliram toj edinstven pregled od listata za direktna i poedinecna obrabotka
            status_t = (t.get("status_pregled") or "").strip()  # go zemam statusot na terminot vo cista forma bez prazni mesta
            if status_t == "откажан":  # ako terminot e otkazan pred toa ne mozeme nisto da menuvame
                return f'Терминот ID {t["termin_ID"]} е откажан, не може да се ажурира.'  # vrakjam jasna poraka za blokiranata akcija
            if status_t == "завршен":  # specijalen tek za veke zavrshen pregled kade samo dx/tx mozat da se ajzuriraat
                ima_dx_tx_vnos = (dijagnoza and not _prazna_dx_tx(dijagnoza)) or (  # proverka dali lekarot vnel barem edno od poliata
                    terapija and not _prazna_dx_tx(terapija)  # ili dijagnoza ili terapija mora da bide validna i ne prazna
                )  # kraj na bulovata proverka za prisustvo na medicinski podatoci
                if not ima_dx_tx_vnos:  # ako voopshto nema noviот vnos za dx ili tx vo porakata na lekarot
                    return (  # vrakjam pouchna poraka so primer kako da go napravi azhuriranjeto pravilno
                        f'Терминот ID {t["termin_ID"]} веќе има статус „завршен“.\n\n'  # objasnuvanje deka terminot veke e zatvoren
                        "За ажурирање наведете дијагноза/терапија, на пр.:\n"  # nasoka shto treba da napishe lekarot za update
                        f'„Додади дијагноза: … и терапија: … на ID {t["termin_ID"]}“.'  # konkreten primer so id na terminot
                    )  # kraj na pouchnata poraka koga nema dx/tx vnesi
                if not _azuriraj_dx_tx(t["termin_ID"], dijagnoza, terapija):  # ako apdejt funkcijata vrati false znaci nema sto da se izmeni
                    return f'Нема промени за термин ID {t["termin_ID"]}.'  # vrakjam jasno izvestuvanje deka nemalo nikakva razlika
                msg = (  # gradam poraka za potvrda na uspeshniot apdejt na medicinskite podatoci
                    f'Прегледот ID {t["termin_ID"]} е веќе завршен — ажурирани се медицинските податоци.'  # glavna potvrdna linija
                    + (f"\nДијагноза: {dijagnoza}" if dijagnoza and not _prazna_dx_tx(dijagnoza) else "")  # dodavam linija so dijagnoza ako e azhurirana
                    + (f"\nТерапија: {terapija}" if terapija and not _prazna_dx_tx(terapija) else "")  # dodavam linija so terapija ako e azhurirana
                )  # kraj na gradenjeto na finalnata poraka za korisnikot
                if nepostoekji:  # ako voedno vo prasanjeto imalo i drugi broevi koi ne pripagaat na ovoj lekar
                    msg += f"\n\nНе најдов: ID {', '.join(str(x) for x in nepostoekji)}"  # ja prikachuvam listata na nevalidni broevi
                return msg  # ja vrakjam celosno sklopena poraka za update na veke zavrshen pregled
            _zavrshi(t["termin_ID"], dijagnoza, terapija)  # ja izvrsushuvam realnata izmena vo bazata za toj pregled so dijagnozata
            msg = _format_uspeh(t, dijagnoza, terapija)  # go generiram ubaviot poedinecen izveshtaj za uspeshen zavrshetok na akcijata
            if nepostoekji:  # ako pokraj uspeshniot termin lekarot vo porakata pishal i neki drugi nepostoecki broevi
                msg += f"\n\nНе најдов: ID {', '.join(str(x) for x in nepostoekji)}"  # ja dopishuvam listata na nevazecki broevi na dnoto
            return msg  # go vrakjam kompletiraniot tekst nazad do korisnikot na interfejsot

        # poveke ID-a odednas
        msg = _zavrshi_mnogu(rows, dijagnoza, terapija)  # ja povikuvam funkcijata za masovno zatvoranje na site potvrdeni broevi vo serija
        if nepostoekji:  # ako vo porakata imalo i broevi koi bile nevazecki ili od tugji rasporedi na lekari
            msg += f"\n\nНе најдов: ID {', '.join(str(x) for x in nepostoekji)}"  # gi dopishuvam tie propushteni broevi na krajot od izveshtajot
        return msg  # go vrakjam masovniot izveshtaj so site detali za uspesno zavrshenite azuriranja vo bazata

    # Edinstven zakazan pregled denes (ako pishat samo "zatvori go terminot" + dx/tx)
    if (  # pametna proverka za kratki intuitivni komandi od lekarite pri rabota vo zivo
        not termin_ids  # uslov da nema vnesen konkreten broj na termin vo porakata
        and not ime  # uslov lekarot da ne go preciziral imeto na pacientot vo tekstot
        and not datum_str  # uslov da nema filter za nekoj specificen datum vo idninata
        and not site  # uslov da ne se raboti za baranje za masovno zatvoranje na site pregledi
        and dijagnoza  # zadolzitelno da ima vneseno tekst koj pretstavuva medicinska dijagnoza
        and terapija  # zadolzitelno lekarot da napishal kakva terapija propishuva za pacientot
    ):  # kraj na slozeniot usloven uslov za intuitivno zatvoranje
        denes = date.today().isoformat()  # go zemam deneshniot sistemski datum na serverot vo standarden string format
        eden = _najdi_site_zakazani(doctor_id, denes)  # pravam selekcija na site aktivni pregledi kaj doktorot za denes
        if len(eden) == 1:  # ako lekarot vo momentov ima tocno eden edinstven zakazan pregled na svojot raspored za denes
            t = eden[0]  # pretpostavuvam deka se raboti za toj tekoven pregled i go zemam za obrabotka
            _zavrshi(t["termin_ID"], dijagnoza, terapija)  # go zatvoram pregledot vo bazata i gi snimam dijagnozata i terapijata
            return _format_uspeh(t, dijagnoza, terapija)  # go vrakjam finalniot ubav izveshtaj za uspesno poedinecno zatvoranje

    # SLUCAJ 3: samo ime / datum (staro odnesuvanje)
    if not ime and not datum_str:  # ako po site dosegashni filtri nemame nitu ime nitu broj nitu datum za prebaruvanje
        return (  # vrakjam detalna pomoshna poraka so primeri kako pravilno se koristi ovaa funkcija vo sistemot
            'За да завршам преглед ми треба: пациент, ID, еден денешен термин, '  # objasnuvanje koi se potrebnite parametri
            'или прво „Прикажи ми термините" (па повтори со дијагноза/терапија).\n'  # sovet za prethodno pregleduvanje na rasporedot
            'Примери:\n'  # pocetok na delot so praktichni tekstualni primeri za lekarite
            '• „Затвори термин ID 42 со дијагноза: … и терапија: …"\n'  # primer so koristenje na tochen broj na termin vo sistemot
            '• „Заврши го прегледот на Петар Иванов со дијагноза: …"\n'  # primer so prebaruvanje po ime na pacient vo bazata
            '• „Заврши ги сите денешни прегледи"'  # primer za masovna akcija vrz site tekovni pregledi
        )  # kraj na stringot na pomoshnata poraka so upatstva

    rows = _najdi_termin(doctor_id, None, ime, datum_str)  # prebaruvam vo bazata so kombiniranite filtri za ime i datum kaj doktorot
    if not rows:  # ako po toa kombinirano prebaruvanje ne se pronajde soodveten red vo bazata na podatoci
        return _poraka_ne_najden_termin(doctor_id, ime or None)  # ja povikuvam pomoshnata funkcija za ubavo prikazuvanje na greshkata

    if len(rows) > 1:  # ako filterot po ime vratil poveke od eden aktiven pregled na rasporedot
        lista = "\n".join(  # gi spojuvam site pronajdeni opcii vo jedna ubava pregledna tekstualna lista
            f"• ID {r['termin_ID']}: {r['ime_pacient']} — {format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])}"  # prikazuvam broj ime datum i tochen chas za izbor
            for r in rows[:6]  # go ogranicuvam prikazot na najmnogu shest opcii so cel zachuvuvanje na chist interfejs
        )  # kraj na listickata kompresija za prikaz na duplikati
        prv_id = rows[0]['termin_ID']  # go zemam prviot broj od lista kako predlog za polesno kopiranje vo komandata
        site_id = ", ".join(str(r['termin_ID']) for r in rows[:6])  # pravam lista od site broevi oddeleni so zapirka za masovna akcija
        return (  # vrakjam poraka koja bara od lekarot dopolnitelno da precizira so koj tocno broj saka da raboti
            "Најдов повеќе закажани прегледи. Може со ID или сите:\n" + lista  # ja prikachuvam generiranata lista so opcii za izbor
            + f'\n\nПример (еден): „Заврши термин ID {prv_id}".'  # davam primer kako se zatvorat samo eden konkreten pregled od ponudenite
            + f'\nПример (повеќе): „Заврши термини {site_id}".'  # davam primer za zatvoranje na nekolku izbrani broevi od listata
            + '\nПример (сите): „Заврши ги сите".'  # primer kako da gi zatvori site pronajdeni pregledi odednas so edna naredba
        )  # kraj na stringot za razreshuvanje na poveke pronajdeni termini po ime

    t = rows[0]  # ako ima tocno eden pronajden termin po ime go zemam nego kako tochen izbor za izmena
    _zavrshi(t["termin_ID"], dijagnoza, terapija)  # go izvrshuvam finalniot apdejt vo bazata so snimeni medicinski beleshki
    return _format_uspeh(t, dijagnoza, terapija)  # go vrakjam finalniot izveshtaj za uspesno poedinecno zatvoranje na pregledot


def _format_uspeh(t: dict, dijagnoza: str | None, terapija: str | None) -> str:  # pomoshna funkcija za ubavo formatiranje na uspeshniot rezultat
    extra = ""  # definiram pocetna prazna tekstualna promenliva za dopolnitelnite medicinski beleshki
    if dijagnoza:  # ako vo ramkite na pregledot bila uspesno zacuvana dijagnoza vo bazata
        extra += f"\nДијагноза: {dijagnoza}"  # go dodavam tekstot na dijagnozata vo noviot red od izveshtajot
    if terapija:  # ako lekarot propishal i vo bazata bila snimena terapija so lekovi
        extra += f"\nТерапија: {terapija}"  # ja lepam terapijata kako posleden red vo medicinskiot izveshtaj
    return (  # go vrakjam komplektniot ubav tekstualen izveshtaj za potvrda na akcijata kaj lekarot
        f"Прегледот е означен како завршен.\n\n"  # glavna naslovna poraka za uspesno zavrshena operacija vo sistemot
        f"ID: {t['termin_ID']}\n"  # go prikazuvam id brojot na zatvoreniot pregled od bazata
        f"Пациент: {t['ime_pacient']}\n"  # go ispisuvam imeto na pacientot za potvrda na identitetot
        f"Кога: {format_datum_i_vreme(t['datum_pregled'], t['vreme_pregled'])}"  # go dodavam tochniot datum i chas koga se izvrshil pregledot
        f"{extra}"  # gi lepam dopolnitelnite redovi za dijagnoza i terapija dokolku bile vneseni
    )  # kraj na stringot za ubav prikaz na uspehot