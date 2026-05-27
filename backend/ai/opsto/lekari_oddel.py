import re                                            
from typing import Any                             
from ai._kernel.oddel_resolver import format_lista_oddeli, resolve_oddel
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.db_helpers import db_cursor
from ai.pacient.slobodni_termini import (
    lekar_od_zakazi_kontekst,                        # zema lekarot od prethoden kontekst (od dijalog)
    prasanje_e_drugi_lekari_specijalnost,            # dali e prashanje „drugi lekari od istata oblast"
)

# Regex sho najduva „koj/koi/koj/koi" sledeno od „lekar" — pochetok na prashanje za lekar(i)
# \b = granica na zbor; re.UNICODE da raboti so kirilica; IGNORECASE da ne ni e gajle za bukvi
_RE_KOJ_KOI_LEKARI = re.compile(r"\b(кој|кои|koj|koi)\s+лекар", re.UNICODE | re.IGNORECASE)
# Regex sho najduva „odelot/oddelot za" — naveduva oddel po ime
# (?:оделот|одделот|одел|оддел) — bilo koja varijanta na zborot
# (?:от|о)? — opcionalno „ot/o" na kraj
_RE_ODELOT_ZA = re.compile(r"(?:оделот|одделот|одел|оддел)(?:от|о)?\s+за", re.UNICODE | re.IGNORECASE)
# Regex za kratko prashanje od tipot „на Урологија" / „на Кардиологија"
# ^ — pochetok na string; .+ — bilo kakov tekst posle „на"
_RE_NA_SPECIALTY = re.compile(r"^на\s+(.+)$", re.UNICODE | re.IGNORECASE)

# Klucni delovi na zborovi sho se javuvaat vo prashanjeto za oddel/specijalnost
# (gi koristime kako brz „dovolen" priznak deka korisnikot zboruva za oddel)
SPECIJALNOSTI = (
    "уролог", "кардиолог", "гинеколог", "невролог",  # urologija, kardiologija, ginekologija, neurologija
    "радиолог", "педијатр", "ортопед", "онколог",    # radiologija, pedijatrija, ortopedija, onkologija
    "дерматолог", "офталмолог", "интерн", "хирург",   # dermatologija, oftalmologija, internа medicina, hirurgija
    "анестез", "лаборатор", "оториноларинголог", "пластич",  # anesteziologija, laboratorija, ORL, plastichna hir.
    "kardiolog", "urolog", "ginekolog", "nevrolog",  # latinica varijanti — koristni za pretrazha
    "radiolog", "pedijatr", "ortoped", "onkolog",
    "dermatolog", "oftalmolog", "hirurg",
    "оддел", "одел", "одделение", "специјалност",    # opshto zborovi za oddel/specijalnost
    "област", "specijalnost", "oblast", "oddel",     # latinica varijanti
)


# Funkcija sho proveruva dali prashanjeto e KRATKO i naveduva oddel bez zbor „lekar"
# Pr. „На урологија" / „На општа хирургија" / „Кардиологија"
def _e_prasanje_za_oddel_kratko(p: str) -> bool:
    p = re.sub(r"^[?!.\s]+|[?!.\s]+$", "", (p or "").strip())  # iscisti gi punktuaciite/prazni mesta na pochetok/kraj
    if not p:                                        # ako ostatokot e prazno → ne e validno
        return False
    # Ako spomenuva zborovi za zakazhuvanje/termini → ne e prashanje za oddel
    if any(x in p for x in ("закажи", "закажување", "термин", "слободен", "слободна", "преглед кај", "otkazi", "zakazi")):
        return False
    # Ako ima „opshta" + specijalnost (pr. „општа хирургија") → e prashanje za oddel
    if any(x in p for x in ("општа", "opsta")) and any(x in p for x in SPECIJALNOSTI):
        return True
    # Probaj go regex-ot „на X" — ako se sovpaga, X e fragmentot posle „на"
    m = _RE_NA_SPECIALTY.match(p)
    if m:                                            # imame sovpagjanje
        frag = m.group(1).strip()                    # zemi go fragmentot (X od „на X")
        if any(x in frag for x in SPECIJALNOSTI):    # ako fragmentot ima specijalnost
            return True
        # Ili ima „opshta" + <= 4 zbora (pr. „opshta hirurgija")
        if any(x in frag for x in ("општа", "opsta")) and len(frag.split()) <= 4:
            return True
    # Kratko prashanje (do 4 zbora) + ima specijalnost → da
    if len(p.split()) <= 4 and any(x in p for x in SPECIJALNOSTI):
        return True
    return False                                     # inaku ne e za oddel


# Funkcija sho proveruva dali prashanjeto e za LISTA lekari po oddel
def prasanje_e_lekari_po_oddel(prasanje: str) -> bool:
    """Dali korisnikot bara lista lekari po oddel (ne po konkretno ime)?"""
    if not prasanje or not prasanje.strip():         # prazno prashanje → ne e
        return False
    p = transliterijaj(prasanje).lower()             # latinica → kirilica + mali bukvi (poednostavna sporedba)
    if "дежур" in p or "dezur" in p:                 # ako e za „dezhurni lekari" → toa e drug handler
        return False
    # Prosti frazi koi 100% znachat „lekari po oddel"
    if any(x in p for x in (
        "кои лекари", "кои доктори", "кој лекари", "кој лекар",      # standardni „koi/koj lekari"
        "лекари на", "лекари од", "лекари по",                       # „lekari na/od/po"
        "лекари од областа", "лекари од област",                     # „lekari od oblasta"
        "на одделот", "на оделот", "одделот за", "оделот за",        # „na oddelot/odelot za"
        "lekari od", "lekari po", "lekari na",                        # latinica varijanti
        "koi lekari", "koj lekari",
    )):
        return True                                  # direktno prepoznato
    # „Koj/koi + lekar..." kako pochetok na prashanje
    if _RE_KOJ_KOI_LEKARI.search(p):
        return True
    # „Oddelot za..." + zbor za lekar/doktor → da
    if _RE_ODELOT_ZA.search(p) and any(x in p for x in ("лекар", "лекари", "доктор", "доктори", "lekari", "doktori")):
        return True
    # „Prikazhi/pokazi lekari" — molba za listanje
    if any(x in p for x in ("прикажи", "прикази", "покажи", "prikazi", "pokazi", "прикажете")) and any(
        x in p for x in ("лекари", "lekari", "доктори", "doktori")
    ):
        return True
    # Generalno: ima zbor „lekari/doktori" + nekoja specijalnost/oddel
    if any(x in p for x in ("лекари", "lekari", "доктори", "докторите")) and any(x in p for x in SPECIJALNOSTI):
        return True
    # Kratko prashanje koe naveduva samo oddel (bez zbor „lekari")
    if _e_prasanje_za_oddel_kratko(p):
        return True
    return False                                     # inaku ne e prashanje za oddel


# Funkcija sho proveruva dali prashanjeto e za CELIOT tim („koi lekari rabotat vo bolnicata?")
def _site_lekari_vo_ustanova(prasanje: str) -> bool:
    """Prashanje za site lekari (bez konkretno ime na oddel)."""
    p = transliterijaj(prasanje).lower()             # normaliziraj go tekstot
    if not any(w in p for w in ("лекар", "доктор", "специјалист")):  # bez zbor za lekar → ne e
        return False
    # Ako se spomenuva „na/od/za oddel..." — toa e za konkreten oddel, ne za site
    if re.search(r"на\s+оддел", p) or re.search(r"од\s+оддел", p) or re.search(r"оддел(?:от|о)?\s+за", p):
        return False
    # „Vo bolnicata" → site lekari vo institucijata
    if re.search(r"во\s+болниц", p):
        return True
    # „Vo ustanovata" → ista logika
    if re.search(r"во\s+установ", p) or "установа" in p or "установата" in p:
        return True
    # „Vo klinikata"
    if re.search(r"во\s+клиник", p) or "клиниката" in p:
        return True
    # „Kaj vas" — vezhliva forma za pitanje
    if "кај вас" in p:
        return True
    # „Kade se (lekarite)?" — najchesto pitanje za skrol kon #lekari
    if re.search(r"каде\s+(?:се\s+)?(?:наоѓа|сме|се)?\s*(?:лекар|доктор)", p):
        return True
    if re.search(r"kade\s+(?:se\s+)?(?:naogja|naodga|sme|se)?\s*(?:lekar|lekari|doktor)", p):
        return True
    # Direktni frazi
    if any(s in p for s in ("сите лекари", "сите доктори", "листа на лекари", "листа на доктори", "медицински тим", "тимот на лекари")):
        return True
    return False                                     # ne e za celiot tim


# Funkcija sho gi normalizira specijalnostite na lekarite za prikaz vo navigacija
def _specijalnost_od_lekari(oddel: str, lekari: list[dict] | None) -> str:
    """Vraka tochen string na specialty (od baza), za da go filter-ot na frontot raboti."""
    if lekari:                                       # ako imame lekari
        for l in lekari:                             # za sekoj lekar
            s = (l.get("specialty") or l.get("specijalnost") or "").strip()  # zemi go „specialty"
            if s:                                    # prvoto neprazno → vrati go
                return s
    return (oddel or "").strip()                     # fallback: ime na oddel od arg-ot


# Funkcija sho gradi „navigacija" objekt za frontend-ot (skrol + filter)
def navigacija_lekari(oddel: str | None = None, lekari: list[dict] | None = None) -> dict[str, str]:
    """Vraka link kon sekcijata Lekari (so filter po specijalnost ako ima oddel)."""
    nav: dict[str, str] = {"target": "index.html#lekari", "label": "Лекари"}  # bazna struktura na navigacija
    if oddel:                                        # ako e prosleden oddel → dodaj filter
        spec = _specijalnost_od_lekari(oddel, lekari)  # zemi tochen specialty string
        nav["label"] = f"Лекари — {spec or oddel}"   # ubav label na linkot
        nav["specijalnost"] = spec or oddel          # vrednost na filterot
    return nav                                       # vrati ja navigacijata


# Funkcija sho vraka odgovor + navigacija za „site lekari vo bolnicata"
def odgovor_navigacija_lekari(oddel: str | None = None) -> dict[str, Any]:
    """Kratka poraka + skrol kon #lekari (po opcija — so filter za oddel)."""
    # Lazy import — za da izbegneme circular import megu lekari_oddel i slobodni_termini
    from ai.pacient.slobodni_termini import zimi_site_lekari
    lekari = zimi_site_lekari()                      # site lekari od bazata (SELECT * FROM Doctors)
    n = len(lekari) if lekari else 0                 # kolku ima sega
    if oddel:                                        # ako imame oddel → poraka so filter
        intro = (
            f'Ве пренасочувам кон делот „Лекари" со филтер за „{oddel}". '
            "На екранот ќе ги видите само лекарите од таа специјалност."
        )
    elif n == 0:                                     # nema lekari vo bazata → uchtiv tekst
        intro = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            "Моментално нема регистрирани лекари во системот."
        )
    else:                                            # normalen scenarij — kazhi kolku ima
        intro = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            f"На екранот ќе ја видите листата со {n} лекари — "
            "можете да пребарувате по име или специјалност и да закажете преглед."
        )
    return {"odgovor": intro, "navigacija": navigacija_lekari(oddel)}  # gotov odgovor


# Funkcija sho gradi edna linija „- Д-р Име Презиме"
def _linija_lekar(l: dict) -> str:
    """Format na edna stavka vo lista (samo edno „Д-р", bez dupliranje)."""
    return f"- Д-р {l.get('name', '').strip()} {l.get('surname', '').strip()}".strip()


# Funkcija sho gradi naslov („На одделот за... работат N лекари:")
def _naslov_lista_lekari(oddel_ime: str, lekari: list[dict], lekar_ref: dict | None, drugi_od_istata: bool) -> str:
    """Naslov nad listata lekari (razlichen ako e „drugi od istata specijalnost")."""
    # Scenarij: korisnikot prashal „daj drugi lekari od istata oblast kako d-r X"
    if drugi_od_istata and lekar_ref:
        ref = f"д-р {lekar_ref.get('name', '')} {lekar_ref.get('surname', '')}".strip()  # ime na referentniot lekar
        spec = (oddel_ime or lekar_ref.get("specialty") or "").strip()  # specijalnost
        if spec:                                     # ako znaeme specijalnost → vmetni ja vo nasov
            return f"Лекари кои работат во истата специјалност како {ref} ({spec}) се:"
        return f"Лекари кои работат во истата специјалност како {ref} се:"
    # Normalen scenarij: ako pochnuva so „На" → otkucame go imeto bez „На"
    oddel = (oddel_ime or "").strip()
    if oddel.lower().startswith("на "):              # ako veke pochnuva so „на"
        oddel = oddel[3:].strip()                    # iskluchi go „на " (3 znaci)
    return f'На одделот за „{oddel}" работат ({len(lekari)} лекари):'


# Funkcija sho gradi zatvoracha rechenica pod listata (kratko sumarno)
def _sledna_poraka_lekari_oddel(oddel_ime: str, lekari: list[dict]) -> str:
    """Posledna rechenica — kratko summary po listata (bez detali za termini)."""
    oddel = (oddel_ime or "").strip()                # normaliziraj
    # Ako ima samo eden lekar — direktno spomeni go
    if len(lekari) == 1:
        l = lekari[0]
        ime = f"Д-р {l.get('name', '').strip()} {l.get('surname', '').strip()}".strip()  # ime na lekarot
        return (
            f'{ime} работи на одделот за „{oddel}".\n'
            "За повеќе информации (работно време, слободни термини, закажување) "
            "прашајте — Ви стојам на располагање."
        )
    # Pove'kje lekari — pokazhi prvi 4 + „uste N"
    iminja = ", ".join(
        f"д-р {l.get('name', '').strip()} {l.get('surname', '').strip()}".strip()
        for l in lekari[:4]                          # prvi 4 lekari
    )
    if len(lekari) > 4:                              # ako ima poveke od 4 → „и уште N"
        iminja += f" и уште {len(lekari) - 4}"
    return (
        f'Лекарите ({iminja}) работат на одделот за „{oddel}".\n'
        "За повеќе информации за конкретен лекар прашајте — Ви стојам на располагање."
    )


# Funkcija sho zima lekari od bazata po specijalnost (oddel)
def _zimi_lekari_od_oddel(oddel: str) -> list[dict]:
    """SELECT lekari kade Doctors.specialty == oddel (po sortirano prezime)."""
    try:                                             # SQL operaciite mozhat da puknat → try/except
        # db_cursor() e context manager — sam otvora i zatvora konekcija
        with db_cursor() as (_, cur):                # (_, cur) — ne ni treba conn, samo cursor
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
                ORDER BY surname, name
                """,
                (oddel,),                            # parametri — tuple so eden element
            )
            return list(cur.fetchall())              # vraka lista od dict-ovi {doctor_ID, name, ...}
    except Exception as e:                           # ako neshto pukne (SQL/konekcija) → log i prazno
        print(f"[lekari_oddel] greshka pri SELECT lekari: {e}")
        return []                                    # nikogash ne hvrlame greshka nagore


# GLAVNA FUNKCIJA — handler za intent „lekari_oddel" (se vika od handlers.py)
def odgovori_za_lekari_oddel(prasanje: str, kontekst: dict | None = None) -> str | dict[str, Any]:
    """Vraka odgovor (string ili dict so „odgovor", „navigacija", „kontekst")."""

    # Scenarij 1: korisnikot prashuva za CELIOT tim → skrol kon #lekari
    if _site_lekari_vo_ustanova(prasanje):
        return odgovor_navigacija_lekari()           # vednash izlez so navigacija

    # Promenlivi za scenario „drugi lekari od istata specijalnost"
    oddel_ime: str | None = None                     # tochno ime na oddel od bazata
    exclude_doctor_id: int | None = None             # lekar koj go isklucuvame (od kontekst)
    lekar_ref: dict | None = None                    # referencen lekar (od prethoden dijalog)
    drugi_od_istata = prasanje_e_drugi_lekari_specijalnost(prasanje)  # dali e „drugi od istata oblast"
    site_oddeli: tuple[str, ...] = ()                # site oddeli (za fallback poraka so lista)

    # Ako e „drugi lekari od istata specijalnost", probaj da go zememe lekarot od kontekst
    if drugi_od_istata:
        lekar_ctx = lekar_od_zakazi_kontekst(kontekst)  # zemi go lekarot od dijalog-kontekst
        if lekar_ctx:                                # ako imame referenten lekar
            lekar_ref = lekar_ctx
            oddel_ime = (lekar_ctx.get("specialty") or "").strip() or None  # specialty od kontekst
            exclude_doctor_id = int(lekar_ctx["doctor_ID"])  # isklucuvame go nego od listata

    # Scenarij 2: nemame oddel od kontekst → probaj da go izvlechime od prashanjeto
    resolved = resolve_oddel(prasanje) if not oddel_ime else None  # AI + pravila izvlekuvaat oddel
    if resolved:                                     # imame rezultat od resolver
        site_oddeli = resolved.site_oddeli           # site mozhni oddeli (za fallback)
        # Specijalen sluchaj: AI e nedostapen (busy/rate limit)
        if resolved.poraka_greska == "_ai_busy":
            return "Привремено сум зафатен. Те молам обиди се повторно за неколку секунди."
        # Specijalen sluchaj: korisnikot prashal „opshta hirurgija" — vo baza ima poveke pododdeli
        if resolved.poraka_greska == "_hirurgija_pododdeli":
            from ai._kernel.oddel_resolver import _hirurgiski_pododdeli  # lazy import
            pod = _hirurgiski_pododdeli(resolved.site_oddeli)  # site hirurshki specijalnosti
            linii = pod[:12] if pod else []          # prvi 12 (da ne se prepolnuva chat-ot)
            # Pomoshna linija za „uste N" ako ima poveke
            ostatok = f"\n- … и уште {len(pod) - len(linii)}" if len(pod) > len(linii) else ""
            return (
                'Немам оддел со точно име „Хирургија" (општа хирургија).\n\n'
                "Во системот се регистрирани овие хируршки специјалности:\n"
                + "\n".join(f"- {o}" for o in linii) + ostatok
                + "\n\nПрашајте конкретно, на пр.:\n"
                '„Кои лекари се на одделот за Неврохирургија?"'
            )
        # Uspeh — zememe go tochnoto ime na oddel od resolver-ot
        if resolved.ok and resolved.oddel:
            oddel_ime = resolved.oddel
    elif not site_oddeli:
        # Nema resolved (sluchaj koga drugi_od_istata e True no nema lekar od kontekst)
        from ai._kernel.oddel_resolver import zimi_site_oddeli  # lazy import
        site_oddeli = zimi_site_oddeli()             # ucitaj lista oddeli za fallback poraka

    # Scenarij 3: ne ni uspe da izvlechime oddel → vrati upatstvo + lista oddeli
    if not oddel_ime:
        # Posledna proverka: mozhebi e za celiot tim (predviduvame edge cases)
        if _site_lekari_vo_ustanova(prasanje):
            return odgovor_navigacija_lekari()
        # Gradenje fallback odgovor so primeri i lista oddeli
        delovi = [
            'Ако прашувате за конкретен оддел, наведете го (на пр.: „Кои лекари се на Кардиологија?").',
            'За целиот тим: „Кои лекари работат во болницата?" или „Каде се лекарите?".',
            "",                                       # prazen red za vizuelno razgraduvanje
            format_lista_oddeli(site_oddeli),         # format-irana lista na site oddeli
        ]
        return "\n".join(delovi)                     # spoji gi vo eden tekst

    # Imame oddel — zememe lekari od bazata
    method = resolved.method if resolved else "kontekst_lekar"  # za debug log
    print(f"[lekari_oddel] оддел={oddel_ime!r} method={method}")  # log za debugging

    lekari = _zimi_lekari_od_oddel(oddel_ime)        # SQL: SELECT lekari WHERE specialty = oddel_ime
    # Ako e „drugi od istata specijalnost", iskluci go referentniot lekar od listata
    if exclude_doctor_id is not None:
        lekari = [l for l in lekari if int(l["doctor_ID"]) != int(exclude_doctor_id)]

    # Scenarij 4: nema lekari za toj oddel → uchtiv odgovor + lista oddeli
    if not lekari:
        if exclude_doctor_id is not None:            # ako bila „drugi od istata"
            return (
                f'На специјалноста „{oddel_ime}" нема други регистрирани лекари '
                "освен оној од претходната порака.\n\n"
                "Можете да закажете кај него (напишете го часот) или да изберете "
                "друга специјалност од листата:\n\n"
                + format_lista_oddeli(site_oddeli)
            )
        # Standardno: nema lekari za toj oddel
        return (
            f'На одделот „{oddel_ime}" моментално нема регистрирани лекари.\n\n'
            + format_lista_oddeli(site_oddeli)
        )

    # Gradenje na tekstualen odgovor: naslov + redovi + zatvoracha rechenica
    naslov = _naslov_lista_lekari(                   # generiraj naslov („На одделот... работат N лекари:")
        oddel_ime or "",
        lekari,
        lekar_ref,
        drugi_od_istata and exclude_doctor_id is not None,
    )
    redovi = [naslov, ""]                            # pochni so naslov + prazen red
    for l in lekari:                                 # za sekoj lekar
        redovi.append(_linija_lekar(l))              # dodaj „- Д-р Име Презиме"
    redovi.append("")                                # prazen red pred zatvoracha rechenica
    sledna = _sledna_poraka_lekari_oddel(oddel_ime or "", lekari)  # generiraj zatvoracha
    redovi.append(sledna)                            # dodaj ja
    sablon = "\n".join(redovi)                       # spoji se vo eden tekst (rezerven ako AI padne)

    # Podgotvi strukturirani podatoci za AI formatter-ot (toj pravi „polished" odgovor)
    lista_lekari = []                                # ke ja polnime so dict-ovi za sekoj lekar
    for l in lekari:                                 # iteriraj niz lekari
        lista_lekari.append(                         # dodaj nov dict
            {
                "ime_prezime": f"{l.get('name', '')} {l.get('surname', '')}".strip(),  # cel naslov ime+prezime
                "email": (l.get("email") or "").strip() or None,  # email (ili None ako e prazno)
            }
        )
    # Site podatoci sho gi treba AI-promptot za formatiranje
    podatoci = {
        "naslov": naslov,                            # naslov nad listata
        "oddel": oddel_ime,                          # ime na oddel (za pominuvanje na AI)
        "broj_lekari": len(lekari),                  # kolku lekari ima vo listata
        "drugi_lekari_ist_oddel": drugi_od_istata and exclude_doctor_id is not None,  # flag
        "lekari": lista_lekari,                      # podgotvenata lista
        "sledna_akcija": sledna,                     # zatvoracha rechenica
    }
    # AI go polishira odgovorot; ako ne uspee — vrakja `sablon` (fallback)
    odgovor_tekst = formatiraj_odgovor_so_ai(
        "lekari_oddel",                              # ime na promptot vo prompts/ (za logiranje)
        podatoci,                                    # strukturirani podatoci za AI
        sablon,                                      # rezerven tekst ako AI padne
        prasanje=prasanje,                           # originalnoto prashanje (za AI da go razbere)
    )

    # Sochuvaj go kontekstot za sledni prashanja (npr. „slobodni kaj prviot")
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}  # kopija na postojniot ili nov
    ctx["last_oddel"] = oddel_ime                    # pamti go odelot za sledna poraka
    ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in lekari]  # IDs na lekari od listata
    if len(lekari) == 1:                             # ako ima samo eden lekar → zapamti go kako „last_doctor"
        ctx["last_doctor_id"] = int(lekari[0]["doctor_ID"])

    # Vrati kompletna struktura — handlers.py ke ja prosledi do frontend-ot
    return {
        "odgovor": odgovor_tekst,                    # final-niot tekst za chat-ot
        "navigacija": navigacija_lekari(oddel_ime, lekari),  # objekt za skrol kon #lekari
        "kontekst": ctx,                             # sochuvan kontekst za sledni prashanja
    }
