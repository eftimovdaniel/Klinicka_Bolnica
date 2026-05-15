"""
Аплицирање за оглас за работа преку AI агент.

Flow:
1) Корисник: „Сакам да аплицирам за кардиолог"
2) Ако не е логиран како пациент → бара логин.
3) Се бара совпаѓање со активен оглас (Vrabotuvanje).
4) Се прашува за број на медицинска лиценца (опционален но препорачлив).
5) Се запишува во `prijaveni_lekari`.

Сите чекори се водат преку `kontekst` dict кој фронтендот го паметИ.
"""

import json
import re
from datetime import datetime

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.db_helpers import as_dict
from ai._kernel.groq_client import ask_ai
from ai._kernel.transliteracija import transliterijaj
from vrabotuvanje_helpers import fetch_aktivni_oglasi_rows, format_rok_datum

NAV_KARIERA = {"target": "index.html#kariera", "label": "Кариера"}


PROMPT_POZICIJA = """
Ти си систем што извлекува позиција за работа од прашање.

Корисникот сака да аплицира за работа во болница. Извлечи го името на
позицијата за која аплицира.

Врати САМО JSON:
{"pozicija": "<име на позицијата>" | null}

Правила:
- Корисникот пишува на македонски (можно е и латиница).
- Прифатени примери: „кардиолог", „хирург", „анестезиолог", „медицинска сестра",
  „гинеколог", „педијатар", „радиолог", „интернист", „уролог" итн.
- Ако корисникот пишува на латиница, врати на кирилица: „kardiolog" → „Кардиолог".
- Ако позицијата НЕ е јасна → null.
- „сакам да аплицирам за работа", „да работам кај вас", „вработување" БЕЗ
  конкретна специјалност/оддел → null (не „работа" како позиција).
- Ако корисникот залепи цел **оглас за работа** (на пр. „Се вработува медицинска сестра…"),
  извлечи ја позицијата од текстот (на пр. „Медицинска сестра").

БЕЗ markdown, БЕЗ објаснувања.
""".strip()


PROMPT_LICENCA = """
Ти си систем што извлекува број на медицинска лиценца од одговор.

Корисникот ти прати порака која може да содржи број на лиценца.
Врати САМО JSON:
{"licenca": "<број (само цифри)>" | null, "preskoki": true/false}

Правила:
- Извлечи го бројот (само цифрите). Пр. „Бројот ми е 12345" → "12345".
- Ако корисникот напише „немам", „преска", „пропушти", „не сакам" → preskoki: true, licenca: null.
- Ако не е јасно → licenca: null, preskoki: false.

БЕЗ markdown.
""".strip()


def _tekst_e_zalepen_oglas(prashanje: str) -> bool:
    """Цел текст на оглас (копиран од сајт/FB), не само „сакам да аплицирам“."""
    p = transliterijaj(prashanje).lower()
    ima_oglas = any(
        x in p
        for x in (
            "оглас за работа",
            "oglas za rabota",
            "се вработува",
            "se vrabotuva",
            "можност за аплицирање",
            "moznost za apliciranje",
            "рок за пријавување",
        )
    )
    ima_pozicija = any(
        x in p
        for x in (
            "медицинск",
            "сестр",
            "лекар",
            "доктор",
            "гинекол",
            "гиникол",
            "акауш",
            "кардиол",
            "хирург",
            "одделот",
        )
    )
    return ima_oglas and ima_pozicija


def _izvlechi_pozicija_od_oglas_pravila(prashanje: str) -> str | None:
    """Брзо извлекување од типичен текст на оглас (без Groq)."""
    p = transliterijaj(prashanje).lower()
    if "медицинск" in p and "сестр" in p:
        return "Медицинска сестра"
    if "гинекол" in p or "гиникол" in p:
        if "сестр" in p:
            return "Медицинска сестра"
        return "Гинеколог"
    if "акауш" in p:
        return "Акушер"
    if "кардиол" in p:
        return "Кардиолог"
    if "хирург" in p:
        return "Хирург"
    if "урол" in p:
        return "Уролог"
    if "анестез" in p:
        return "Анестезиолог"
    m = re.search(r"\(([^)]+)\)", prashanje)
    if m:
        inner = m.group(1).strip()
        if len(inner) > 3 and len(inner) < 80:
            return inner[0].upper() + inner[1:] if inner else None
    return None


def _baraj_pozicija_za_aplikacija(prashanje: str) -> str | None:
    """Позиција од оглас (правила) или преку AI."""
    if _tekst_e_zalepen_oglas(prashanje):
        poz = _izvlechi_pozicija_od_oglas_pravila(prashanje)
        if poz:
            return poz
    return _izvlechi_pozicija(prashanje)


def _odgovor_bara_pacient_login(kontekst_za_po_login: dict | None, prikaz_pozicija: str) -> dict:
    out: dict = {
        "odgovor": (
            f"Го препознав огласот за работа: {prikaz_pozicija}.\n\n"
            "За да ја испратам апликацијата преку AI, прво треба да се "
            "најавиш како пациент (не како лекар). "
            "Ти ја отворам формата за најава — по најавата напиши «да» "
            "или «сакам да аплицирам» за да продолжиме."
        ),
        "akcija": "otvori_pacient_login",
        "navigacija": NAV_KARIERA,
    }
    if kontekst_za_po_login:
        out["kontekst"] = kontekst_za_po_login
    else:
        out["kontekst"] = None
    return out


def _prasanje_e_opsto_za_rabota(prashanje: str) -> bool:
    """„Аплицирам за работа" без конкретна позиција/специјалност."""
    p = transliterijaj(prashanje).lower()
    if not any(
        w in p
        for w in (
            "аплиц",
            "aplic",
            "пријав",
            "prijav",
            "вработ",
            "vrabot",
            "работа",
            "rabota",
            "работам",
            "rabotam",
        )
    ):
        return False
    spec_hints = (
        "кардиол",
        "хирург",
        "урол",
        "анестез",
        "гинекол",
        "педијат",
        "неврол",
        "ортопед",
        "радиол",
        "интерн",
        "офталм",
        "инфект",
        "психијат",
        "оторин",
        "пулмол",
        "гастро",
        "онкол",
        "сестр",
        "неврохирург",
        "пластич",
        "патолош",
        "медицинск",
    )
    return not any(h in p for h in spec_hints)


def _aktivni_oglasi() -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        rows = fetch_aktivni_oglasi_rows(cur)
        cur.close()
        out: list[dict] = []
        for raw in rows:
            r = as_dict(raw)
            out.append(
                {
                    "id_oglas": r.get("id_oglas"),
                    "pozicija": (r.get("pozicija") or "").strip(),
                    "oddel": (r.get("oddel") or "").strip(),
                    "rok": format_rok_datum(r.get("datum_na_prijavuvanje")),
                }
            )
        return out
    except Exception as e:
        print(f"[apliciraj] lista oglasi: {e}")
        return []
    finally:
        if conn and conn.is_connected():
            conn.close()


def _format_pozicija_oglas(oglas: dict) -> str:
    poz = (oglas.get("pozicija") or "").strip() or "—"
    odd = (oglas.get("oddel") or "").strip()
    if odd and odd.lower() not in poz.lower():
        return f'„{poz}" ({odd})'
    return f'„{poz}"'


def _parse_da_ne(prashanje: str) -> str | None:
    """Враќа 'da', 'ne' или None."""
    p = transliterijaj(prashanje).lower().strip()
    p = re.sub(r"[^\w\sа-яѓќѕџ]+", " ", p, flags=re.IGNORECASE)
    p = re.sub(r"\s+", " ", p).strip()

    ne_frazi = (
        "не сакам",
        "ne sakam",
        "не би",
        "не сак",
        "откажи",
        "odkazi",
        "нема интерес",
        "не ме интересира",
    )
    if p in ("не", "ne", "no") or any(x in p for x in ne_frazi):
        return "ne"
    if p in (
        "да",
        "da",
        "yes",
        "ja",
        "јас",
        "сакам",
        "аплицирај",
        "аплицирам",
        "во ред",
        "ok",
        "okej",
        "okay",
        "се разбира",
    ) or re.search(r"\bда\b", p):
        if "не" not in p and "ne " not in p:
            return "da"

    return None


def _pocni_potvrda_flow(oglas: dict) -> dict:
    """Праша дали сака да аплицира — пред лиценца."""
    pozicija_naslov = oglas["pozicija"]
    id_o = oglas["id_oglas"]
    prikaz = _format_pozicija_oglas(oglas)
    rok = oglas.get("rok")
    rok_linija = f"\nРок за пријава: {rok}." if rok else ""

    return {
        "odgovor": (
            f"Во моментов има отворена позиција за {prikaz}.{rok_linija}\n\n"
            "Дали сакате да аплицирате?\n"
            'Одговорете со „да" или „не".'
        ),
        "kontekst": {
            "intent": "apliciraj_za_rabota",
            "cekam": "potvrda",
            "pozicija": pozicija_naslov,
            "id_oglas": id_o,
            "oddel": oglas.get("oddel") or "",
            "rok": rok or "",
        },
        "navigacija": NAV_KARIERA,
    }


def _oglas_od_kontekst(kontekst: dict) -> dict:
    return {
        "id_oglas": kontekst.get("id_oglas"),
        "pozicija": kontekst.get("pozicija") or "",
        "oddel": kontekst.get("oddel") or "",
        "rok": kontekst.get("rok") or "",
    }


def _pocni_licenca_flow(oglas: dict, pacient: dict) -> dict:
    pozicija_naslov = oglas["pozicija"]
    id_o = oglas["id_oglas"]
    return {
        "odgovor": (
            f"Одлично! Продолжуваме со апликацијата за {_format_pozicija_oglas(oglas)}.\n\n"
            f"Ќе ги користам вашите податоци: "
            f'{pacient.get("ime", "")} {pacient.get("prezime", "")}, '
            f'{pacient.get("email", "")}.\n\n'
            "Те молам испратете го бројот на вашата медицинска лиценца "
            '(само цифри), или напишете „немам" ако не сакате да го '
            "споделите сега."
        ),
        "kontekst": {
            "intent": "apliciraj_za_rabota",
            "cekam": "licenca",
            "pozicija": pozicija_naslov,
            "id_oglas": id_o,
        },
        "navigacija": NAV_KARIERA,
    }


def _odgovor_odbien_aplikacija() -> dict:
    return {
        "odgovor": (
            "Ви благодариме.\n\n"
            'Следете ги огласите во делот „Кариера" на сајтот.\n\n'
            "Доколку подоцна сте заинтересирани, тука сме да го обработиме "
            "вашето барање за работа — слободно пишете повторно кога ќе сакате."
        ),
        "kontekst": None,
        "navigacija": NAV_KARIERA,
    }


def _odgovor_izberi_pozicija(pacient: dict) -> dict:
    """Нема именувана позиција — кратка листа + навигација кон Кариера."""
    oglasi = _aktivni_oglasi()
    if not oglasi:
        return {
            "odgovor": (
                "Моментално нема отворени работни позиции за пријавување.\n\n"
                'Страницата ќе се отвори на делот „Кариера" — проверете повторно подоцна '
                "или контактирајте ја централата."
            ),
            "kontekst": None,
            "navigacija": NAV_KARIERA,
        }

    if len(oglasi) == 1:
        return _pocni_potvrda_flow(oglasi[0])

    linii = [
        "Сакате да аплицирате за работа. Моментално има следниве отворени позиции:",
        "",
    ]
    for o in oglasi:
        linii.append(
            f"• {o['pozicija']} — оддел: {o.get('oddel') or '—'}. "
            f"Рок за пријава: {o.get('rok') or '—'}."
        )
    linii.extend(
        [
            "",
            "Напишете која позиција ве интересира, на пример:",
            '„Сакам да аплицирам за Уролог" или „Аплицирај ме за кардиолог".',
            "Ќе ве водам чекор по чекор (лиценца и потврда).",
            "",
            'Исто така можете да се пријавите преку формата во делот „Кариера" на страницата.',
        ]
    )
    return {
        "odgovor": "\n".join(linii),
        "kontekst": None,
        "navigacija": NAV_KARIERA,
    }


def _izvlechi_pozicija(prashanje: str) -> str | None:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT_POZICIJA)
    print(f"[apliciraj] pozicija AI: {odgovor!r}")
    data = parse_ai_json(odgovor, log_tag="apliciraj_pozicija")
    if data.get("_error"):
        return None
    val = data.get("pozicija")
    return str(val).strip() if val else None


def _izvlechi_licenca(prashanje: str) -> tuple[str | None, bool]:
    """Враќа (licenca, preskoki)."""
    odgovor = ask_ai(f"Одговор: „{prashanje}\"", system_prompt=PROMPT_LICENCA)
    print(f"[apliciraj] licenca AI: {odgovor!r}")
    data = parse_ai_json(odgovor, log_tag="apliciraj_licenca")
    if data.get("_error"):
        return None, False
    licenca = data.get("licenca")
    preskoki = bool(data.get("preskoki"))
    if licenca:
        licenca = re.sub(r"\D", "", str(licenca))
        if not licenca:
            licenca = None
    return licenca, preskoki


def _najdi_aktiven_oglas(pozicija_baranо: str) -> dict | None:
    """
    Пробува да најде активен оглас чија позиција содржи / е содржана во баранatа.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        site = fetch_aktivni_oglasi_rows(cur)
        cur.close()
    except Exception as e:
        print(f"[apliciraj] DB greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()

    if not site:
        return None

    b = pozicija_baranо.lower().strip()

    # 1) Точна еднаквост (case-insensitive)
    for o in site:
        if (o.get("pozicija") or "").strip().lower() == b:
            return o
    # 2) Substring
    for o in site:
        p = (o.get("pozicija") or "").strip().lower()
        if b and (b in p or p in b):
            return o
    return None


def _zapisi_aplikacija(
    id_oglas: int | None,
    pozicija: str,
    ime: str,
    prezime: str,
    email: str,
    telefon: str | None,
    licenca: str | None,
) -> tuple[bool, str]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        denes = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tel_int = None
        if telefon:
            t = re.sub(r"\D", "", str(telefon))
            tel_int = int(t) if t else None
        lic_int = None
        if licenca:
            l = re.sub(r"\D", "", str(licenca))
            lic_int = int(l) if l else None
        cur.execute("""
            INSERT INTO prijaveni_lekari
              (id_oglas, pozicija, ime_lekar, prezime_lekar,
               broj_med_licenca, email, telefon, datum_prijava)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_oglas, pozicija, ime, prezime, lic_int, email, tel_int, denes))
        conn.commit()
        cur.close()
        return True, ""
    except Exception as e:
        print(f"[apliciraj] INSERT greshka: {e}")
        return False, str(e)
    finally:
        if conn:
            conn.close()


def odgovori_za_aplikacija(
    prashanje: str,
    pacient: dict | None,
    kontekst: dict | None,
) -> dict:
    """
    Враќа: { "odgovor": str, "kontekst": dict|None }

    Логика:
    - Ако нема пациент логиран → бара логин.
    - Ако нема активен kontekst → почни нов flow: извлечи позиција, потврди, прашај за лиценца.
    - Ако има активен kontekst со cekam='licenca' → прими лиценца и испрати апликација.
    - Ако има активен kontekst со cekam='potvrduvanje' → потврди и испрати.
    """

    cekam = (kontekst or {}).get("cekam")

    # По најава: продолжи од зачуваниот оглас
    if cekam == "login" and pacient and pacient.get("email"):
        oglas = _oglas_od_kontekst(kontekst or {})
        if oglas.get("id_oglas") and oglas.get("pozicija"):
            return _pocni_potvrda_flow(
                {
                    "id_oglas": oglas["id_oglas"],
                    "pozicija": oglas["pozicija"],
                    "oddel": oglas.get("oddel") or "",
                    "rok": oglas.get("rok") or "",
                }
            )

    if not pacient or not pacient.get("email"):
        if not cekam and (_tekst_e_zalepen_oglas(prashanje) or "аплиц" in transliterijaj(prashanje).lower()):
            baran = _baraj_pozicija_za_aplikacija(prashanje)
            if baran:
                oglas = _najdi_aktiven_oglas(baran)
                if oglas:
                    prikaz = _format_pozicija_oglas(oglas)
                    return _odgovor_bara_pacient_login(
                        {
                            "intent": "apliciraj_za_rabota",
                            "cekam": "login",
                            "pozicija": oglas["pozicija"],
                            "id_oglas": oglas["id_oglas"],
                            "oddel": oglas.get("oddel") or "",
                            "rok": oglas.get("rok") or "",
                        },
                        prikaz,
                    )
                return _odgovor_bara_pacient_login(
                    None,
                    f'„{baran}" (во моментов нема точен активен оглас во системот — провери Кариера)',
                )
        return _odgovor_bara_pacient_login(
            None,
            "аплицирање за работа",
        )

    pozicija = (kontekst or {}).get("pozicija")
    id_oglas = (kontekst or {}).get("id_oglas")

    # === Чекор 1: нов flow — извлечи позиција ===
    if not cekam:
        if _prasanje_e_opsto_za_rabota(prashanje):
            return _odgovor_izberi_pozicija(pacient)

        baran = _baraj_pozicija_za_aplikacija(prashanje)
        if not baran:
            return _odgovor_izberi_pozicija(pacient)

        oglas = _najdi_aktiven_oglas(baran)
        if not oglas:
            return {
                "odgovor": (
                    f'Во моментот нема активен оглас за „{baran}". '
                    "Подолу се сите отворени позиции — изберете друга или проверете "
                    'на делот „Кариера".'
                ),
                "kontekst": None,
                "navigacija": NAV_KARIERA,
            }

        return _pocni_potvrda_flow(oglas)

    # === Чекор 2: потврда (да / не) ===
    if cekam == "potvrda":
        odluka = _parse_da_ne(prashanje)
        if odluka is None:
            prikaz = _format_pozicija_oglas(_oglas_od_kontekst(kontekst or {}))
            return {
                "odgovor": (
                    f"Не разбрав. За позицијата {prikaz} — "
                    'одговорете со „да" ако сакате да аплицирате, или „не" ако не.'
                ),
                "kontekst": kontekst,
            }
        if odluka == "ne":
            return _odgovor_odbien_aplikacija()
        return _pocni_licenca_flow(_oglas_od_kontekst(kontekst or {}), pacient)

    # === Чекор 3: лиценца ===
    if cekam == "licenca":
        licenca, preskoki = _izvlechi_licenca(prashanje)
        if licenca is None and not preskoki:
            return {
                "odgovor": (
                    'Не препознав важечки број на лиценца. Те молам '
                    'прати само цифри (пр. „12345") или напиши „немам" '
                    'за да продолжиме без лиценца.'
                ),
                "kontekst": kontekst,
            }

        ok, err = _zapisi_aplikacija(
            id_oglas=id_oglas,
            pozicija=pozicija or "",
            ime=pacient.get("ime", "") or "",
            prezime=pacient.get("prezime", "") or "",
            email=pacient.get("email", "") or "",
            telefon=pacient.get("telefon"),
            licenca=licenca,
        )
        if not ok:
            return {
                "odgovor": (
                    'Се случи грешка при зачувувањето на апликацијата. '
                    'Те молам обиди се повторно или контактирај ја рецепцијата.'
                ),
                "kontekst": None,
            }

        lic_info = f"Лиценца: {licenca}" if licenca else "Лиценца: (без)"
        return {
            "odgovor": (
                'Готово! Апликацијата е успешно испратена.\n\n'
                f'Позиција: {pozicija}\n'
                f'Кандидат: {pacient.get("ime","")} {pacient.get("prezime","")}\n'
                f'Email: {pacient.get("email","")}\n'
                f'{lic_info}\n\n'
                'Тимот за човечки ресурси ќе те контактира за следните чекори. Среќно!'
            ),
            "kontekst": None,
        }

    # Безбедност: непознат cekam – чисти го контекстот
    return {
        "odgovor": 'Те молам обиди се повторно: „Сакам да аплицирам за [позиција]".',
        "kontekst": None,
    }
