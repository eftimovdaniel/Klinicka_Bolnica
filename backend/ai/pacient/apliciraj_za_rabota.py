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
from ai._kernel.groq_client import ask_ai
from vrabotuvanje_helpers import fetch_aktivni_oglasi_rows


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

    if not pacient or not pacient.get("email"):
        return {
            "odgovor": (
                'За да аплицираш за работа преку AI асистентот, прво треба да се '
                'најавиш како пациент. Ти ја отворам формата за најава – '
                'по најавата веднаш ќе ти ја испратам апликацијата.'
            ),
            "kontekst": None,
            "akcija": "otvori_pacient_login",
        }

    cekam = (kontekst or {}).get("cekam")
    pozicija = (kontekst or {}).get("pozicija")
    id_oglas = (kontekst or {}).get("id_oglas")

    # === Чекор 1: нов flow — извлечи позиција ===
    if not cekam:
        baran = _izvlechi_pozicija(prashanje)
        if not baran:
            return {
                "odgovor": (
                    'Не разбрав за која позиција сакаш да аплицираш. '
                    'Пробај: „Сакам да аплицирам за Кардиолог" или '
                    '„Аплицирај ме за хирург".'
                ),
                "kontekst": None,
            }

        oglas = _najdi_aktiven_oglas(baran)
        if not oglas:
            return {
                "odgovor": (
                    f'Во моментот нема активен оглас за „{baran}". '
                    'Кликни на „Кариера" за да ги видиш сите отворени позиции.'
                ),
                "kontekst": None,
            }

        # Прашаме за лиценца
        pozicija_naslov = oglas["pozicija"]
        id_o = oglas["id_oglas"]
        return {
            "odgovor": (
                f'Одлично! Аплицираш за „{pozicija_naslov}" '
                f'({oglas.get("oddel") or "—"}).\n\n'
                f'Ќе ги користам твоите податоци: '
                f'{pacient.get("ime", "")} {pacient.get("prezime", "")}, '
                f'{pacient.get("email", "")}.\n\n'
                'Те молам прати го бројот на твојата медицинска лиценца '
                '(само цифри), или напиши „немам" ако не сакаш да го '
                'споделиш сега.'
            ),
            "kontekst": {
                "intent": "apliciraj_za_rabota",
                "cekam": "licenca",
                "pozicija": pozicija_naslov,
                "id_oglas": id_o,
            },
        }

    # === Чекор 2: чекаме лиценца ===
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
