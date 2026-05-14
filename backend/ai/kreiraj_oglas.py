import json
import re
from datetime import date, datetime, timedelta
from typing import Optional
from database import get_connection
from ai._kernel.groq_client import ask_ai


# Системски prompt за извлекување оглас податоци
OGLAS_EXTRACT_PROMPT = """
Ти си систем што извлекува податоци за оглас за работа од прашање на корисник.

Корисникот пишува на македонски јазик и опишува каков оглас сака да објави.

ОДГОВОР: Врати САМО валиден JSON во форматот:
{
  "pozicija": "...",       // име на позицијата (пр. „Кардиолог", „Медицинска сестра")
  "oddel": "...",          // име на одделот (мора да биде од листата подолу)
  "datum_na_prijavuvanje": "YYYY-MM-DD" или null,  // рок за пријавување
  "broj_pozicii": null или цел број  // ако пишува „2 позиции", „3 лекари" итн.
}

ПРАВИЛА за извлекување:
1. „pozicija" треба да биде наслов на позицијата на македонски:
   - „кардиолог" → „Кардиолог"
   - „медицинска сестра" → „Медицинска сестра"
   - „специјалист интернист" → „Специјалист интернист"
   - „фармацевт" → „Фармацевт"
   - „радиолог" → „Радиолог"
   - „гинеколог" → „Гинеколог"
   - „анестезиолог" → „Анестезиолог"
   Ако корисникот не спомне специфична позиција → null.

2. „oddel" мора да биде ТОЧНО од листата подолу. Пробај најдобар match:
   - „кардиолог" → „Кардиологија"
   - „гинеколог" → „Акушерство и геникологија"
   - „интернист" → „Интерна Медицина"
   - „радиолог" → „Радиологија"
   - „психијатар" → „Психијатрија"
   Ако позицијата е „медицинска сестра" без специјалност → „Општа медицина".
   Ако не можеш да најдеш match → null.

3. „datum_na_prijavuvanje" — извлечи рок ако е спомнат:
   - „рок 1 јуни" → текова година, „YYYY-06-01"
   - „до 15-ти" → следниот таков ден
   - „рок 30 дена" → null (default ќе биде 30 дена)
   - „за две недели" → null (default ќе биде 14 дена)
   - Ако нема јасен рок → null

4. „broj_pozicii" — ако пишува „2 кардиолози", „три лекари" итн., извлечи го бројот;
   во спротивно null.

5. НЕ додавај markdown (```json), објаснувања, наводници пред/после JSON-от.
   Само ЧИСТ JSON.

ПРИМЕРИ:
- „Креирај оглас за кардиолог" →
  {"pozicija": "Кардиолог", "oddel": "Кардиологија", "datum_na_prijavuvanje": null, "broj_pozicii": null}

- „Сакам да објавам оглас за 2 медицински сестри на хирургија со рок 1 јуни" →
  {"pozicija": "Медицинска сестра", "oddel": "Општа хирургија", "datum_na_prijavuvanje": "2026-06-01", "broj_pozicii": 2}

- „Креирај оглас за гинеколог" →
  {"pozicija": "Гинеколог", "oddel": "Акушерство и геникологија", "datum_na_prijavuvanje": null, "broj_pozicii": null}
""".strip()


# Macedonian months
MAK_MESEC = {
    "јануари": 1, "февруари": 2, "март": 3, "април": 4,
    "мај": 5, "јуни": 6, "јули": 7, "август": 8,
    "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
}


def zimi_site_oddeli() -> list[str]:
    """Чита сите оддели од Oddeli табелата."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel")
        rows = cur.fetchall()
        cur.close()
        return [r["ime_na_oddel"] for r in rows if r.get("ime_na_oddel")]
    except Exception as e:
        print(f"[kreiraj_oglas] greshka pri zimanje oddeli: {e}")
        return []
    finally:
        if conn:
            conn.close()


def izvlechi_oglas_podatoci(prashanje: str) -> dict:
    """
    Користи AI (Groq) да извлече pozicija, oddel, datum_na_prijavuvanje, broj_pozicii.

    Враќа dict:
    {"pozicija": str|None, "oddel": str|None, "datum_na_prijavuvanje": str|None,
     "broj_pozicii": int|None, "_error": str|None}
    """
    oddeli_list = zimi_site_oddeli()
    oddeli_text = "\n".join(f"- {o}" for o in oddeli_list)

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = (
        f"Денешен датум: {denes} ({den_vo_nedela})\n\n"
        f"Постоечки оддели во болницата:\n{oddeli_text}\n\n"
        f"Корисник пишува: „{prashanje}\"\n\n"
        "Извлечи pozicija, oddel, datum_na_prijavuvanje, broj_pozicii и врати JSON."
    )

    odgovor = ask_ai(full_prompt, system_prompt=OGLAS_EXTRACT_PROMPT)
    print(f"[kreiraj_oglas] AI raw: {odgovor!r}")

    # Detektiraj rate limit / greshki
    error_indicators = [
        "Привремено сум преоптоварен",
        "Привремена грешка",
        "не одговори навреме",
        "Не е поставен",
        "Непозната грешка",
        "неочекуван формат",
        "Невалиден API",
    ]
    if any(ind in odgovor for ind in error_indicators):
        return {"_error": odgovor}

    # Исчисти markdown
    cist = odgovor.strip()
    cist = re.sub(r"^```(?:json)?\s*", "", cist)
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        return {
            "pozicija": podatoci.get("pozicija"),
            "oddel": podatoci.get("oddel"),
            "datum_na_prijavuvanje": podatoci.get("datum_na_prijavuvanje"),
            "broj_pozicii": podatoci.get("broj_pozicii"),
        }
    except json.JSONDecodeError as e:
        print(f"[kreiraj_oglas] JSON greshka: {e}, raw: {cist!r}")
        return {
            "pozicija": None,
            "oddel": None,
            "datum_na_prijavuvanje": None,
            "broj_pozicii": None,
        }


def proveri_i_normaliziraj_oddel(oddel: Optional[str]) -> Optional[str]:
    """
    Проверка дали наведениот оддел постои во базата (case-insensitive).
    Враќа точниот стринг од базата или None.
    """
    if not oddel:
        return None
    site = zimi_site_oddeli()
    oddel_lower = oddel.lower().strip()
    for o in site:
        if o.lower() == oddel_lower:
            return o
    # Pobliska promena - sodrzane:
    for o in site:
        if oddel_lower in o.lower() or o.lower() in oddel_lower:
            return o
    return None


def vmetni_oglas_vo_baza(
    pozicija: str,
    oddel: str,
    datum_na_objava: date,
    datum_na_prijavuvanje: date,
    status_oglas: str = "валентен",
) -> Optional[int]:
    """INSERT во Vrabotuvanje. Враќа нов ID или None."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        return new_id
    except Exception as e:
        print(f"[kreiraj_oglas] DB greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()


def format_datum(d: date) -> str:
    """Македонски формат на датум: '15.06.2026'."""
    return d.strftime("%d.%m.%Y")


def odgovori_za_kreiranje_oglas(prashanje: str, lekar: Optional[dict]) -> str:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - целата порака од директорот
        lekar     - dict со податоци за логиран лекар (треба да биде директор)

    Враќа: текстуален одговор за приказ во чатот.
    """
    # 1. Проверка дали корисникот е лекар
    if not lekar or not lekar.get("doctor_ID"):
        return (
            "За да креираш оглас преку AI асистентот, мораш прво да се најавиш "
            "како лекар (директор) горе десно."
        )

    # 2. Проверка дали корисникот е директор (Владко Захариев)
    try:
        from routers.admin import check_admin_access
        if not check_admin_access(lekar.get("doctor_ID")):
            return (
                "Само директорот на болницата може да креира огласи преку AI асистентот."
            )
    except Exception as e:
        print(f"[kreiraj_oglas] greshka pri admin proverka: {e}")
        return "Не можам да ги проверам твоите права во моментов. Обиди се повторно."

    # 3. AI извлекува податоци
    izvleceno = izvlechi_oglas_podatoci(prashanje)
    if izvleceno.get("_error"):
        return izvleceno["_error"]

    pozicija = (izvleceno.get("pozicija") or "").strip()
    oddel_raw = (izvleceno.get("oddel") or "").strip()
    datum_str = izvleceno.get("datum_na_prijavuvanje")
    broj_pozicii = izvleceno.get("broj_pozicii")

    # 4. Валидација - мора позиција + оддел
    if not pozicija and not oddel_raw:
        return (
            'За да креирам оглас, потребно ми е да знам:\n'
            '- Позиција (пр. „Кардиолог", „Медицинска сестра")\n'
            '- Оддел (на кој оддел)\n'
            '- Опционално: рок за пријавување\n\n'
            'Пример: „Креирај оглас за кардиолог со рок 1 јуни"\n'
            'или: „Сакам оглас за 2 медицински сестри на хирургија"'
        )

    if not pozicija:
        return (
            'Не успеав да ја разберам позицијата. Те молам напиши попрецизно.\n\n'
            'Пример: „Креирај оглас за кардиолог на кардиологија"'
        )

    # 5. Проверка/нормализација на оддел
    oddel = proveri_i_normaliziraj_oddel(oddel_raw)
    if not oddel:
        oddeli_site = zimi_site_oddeli()
        primer = ", ".join(f"„{o}\"" for o in oddeli_site[:5])
        return (
            f'Одделот „{oddel_raw}\" не постои во болницата.\n\n'
            f'Постоечки оддели: {primer}, итн.\n\n'
            'Те молам напиши го точното име на одделот.'
        )

    # 6. Парсирај рок (datum_na_prijavuvanje)
    datum_na_objava = date.today()
    datum_na_prijavuvanje = None

    if datum_str:
        try:
            datum_na_prijavuvanje = datetime.strptime(datum_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"[kreiraj_oglas] nevaliden datum: {datum_str}")

    # Ако нема рок од AI, default 30 дена
    if not datum_na_prijavuvanje:
        datum_na_prijavuvanje = datum_na_objava + timedelta(days=30)

    # Дополнителна проверка - рокот не смее да биде во минатото
    if datum_na_prijavuvanje < datum_na_objava:
        return (
            f'Рокот за пријавување ({format_datum(datum_na_prijavuvanje)}) е во минатото. '
            'Те молам наведи валиден рок (минимум денешен датум).'
        )

    # 7. INSERT
    new_id = vmetni_oglas_vo_baza(
        pozicija=pozicija,
        oddel=oddel,
        datum_na_objava=datum_na_objava,
        datum_na_prijavuvanje=datum_na_prijavuvanje,
    )

    if not new_id:
        return (
            "Огласот беше успешно генериран, но не успеав да го зачувам во базата. "
            "Пробај пак за неколку секунди."
        )

    # 8. Успешен одговор
    broj_text = ""
    if broj_pozicii and broj_pozicii > 1:
        broj_text = f" ({broj_pozicii} позиции)"

    return (
        'Огласот е успешно креиран!\n\n'
        f'Позиција: {pozicija}{broj_text}\n'
        f'Оддел: {oddel}\n'
        f'Датум на објава: {format_datum(datum_na_objava)}\n'
        f'Рок за пријавување: {format_datum(datum_na_prijavuvanje)}\n'
        f'Статус: валентен\n\n'
        'Може да го видиш на страната „Кариера" на сајтот.\n'
        f'ID: {new_id}'
    )
