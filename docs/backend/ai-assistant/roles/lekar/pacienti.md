# Лекар: Картон и пациенти

Лекарот може да го прочита целосниот медицински картон на пациент, да ја види историјата на прегледи кај себе, и да запише дијагноза/терапија — сè преку разговор. Сите функции се ограничени на податоци релевантни за тековниот лекар.

> Поврзано: [Лекар (преглед)](../lekar.md) · [Распоред](raspored.md) · [Статистика](statistika.md) ·
> [API: Пациенти](../../../api/pacienti.md) · [API: Термини](../../../api/termini.md)

## Содржина

* [1. Преглед](#1-pregled)
* [2. Медицински картон (`karton_pacient`)](#2-karton)
* [3. Историја на пациент (`istorija_pacient`)](#3-istorija)
* [4. Запис на терапија (`zapishi_terapija`)](#4-terapija)
* [5. Пробај](#5-probaj)

***

## 1. Преглед <a id="1-pregled"></a>

| Намера | Фајл | Дејство |
|--------|------|---------|
| `karton_pacient` | `karton_pacient.py` | Целосен картон: профил + сите прегледи (со дијагнози/терапии) |
| `istorija_pacient` | `istorija_pacient.py` | Историја на прегледи на пациент **кај тековниот лекар** |
| `zapishi_terapija` | `zapishi_terapija.py` | `UPDATE` дијагноза/терапија (по ID или име) |

> **Картон vs историја:** картонот е целосен (сите лекари, профил на пациент); историјата е потесна — само прегледите на тој пациент кај **тековниот** лекар.

***

## 2. Медицински картон (`karton_pacient`) <a id="2-karton"></a>

Groq го извлекува името на пациентот, се бара во табелата `patient`, и потоа се читаат сите прегледи поврзани преку е-поштата. Ако има повеќе пациенти со исто име, асистентот бара прецизирање.

```python
# backend/ai/lekar/karton_pacient.py (избор)
cur.execute(
    "SELECT termin_ID, ime_lekar, specijalnost_termin, datum_pregled, vreme_pregled,"
    "       status_pregled, dijagnoza, terapija, napomena"
    " FROM Termin_pregled"
    " WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))"
    " ORDER BY datum_pregled DESC, vreme_pregled DESC",
    (p["email"] or "",),
)
```

### Реален излез

```text
МЕДИЦИНСКИ КАРТОН
Пациент: Петар Иванов
E-пошта: petar@example.com
Телефон: 070123456
ID на пациент: 15

Вкупно прегледи: 3 (завршени: 2, закажани: 1)

Последни прегледи:

• 17.06.2026 09:30 — завршен (ID 42)
  Лекар: Александар Серафимов (Кардиологија)
  Дијагноза: Мигрена
  Терапија: Аналгетик 2x дневно
```

***

## 3. Историја на пациент (`istorija_pacient`) <a id="3-istorija"></a>

Потесна функција — ги прикажува само прегледите на тој пациент **кај тековниот лекар** (`doctor_ID` влегува во условот). Корисна за брз преглед колку пати лекарот го видел пациентот и со каков исход.

```python
# backend/ai/lekar/istorija_pacient.py (избор)
sql = (
    "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled,"
    "       status_pregled, dijagnoza, terapija"
    " FROM Termin_pregled"
    " WHERE doctor_ID = %s"        # само кај тековниот лекар
)
# + LOWER(ime_pacient) LIKE ... за секој дел од името
```

### Реален излез

```text
Историја на „Петар Иванов" кај тебе (вкупно 3 прегледи):
• Завршени: 2
• Закажани: 1
• Откажани: 0

Последни прегледи:
• 17.06.2026 09:30 — завршен (ID 42)
  Дијагноза: Мигрена
• 10.05.2026 11:00 — завршен (ID 31)
  Дијагноза: Главоболка
```

***

## 4. Запис на терапија (`zapishi_terapija`) <a id="4-terapija"></a>

Лекарот запишува дијагноза и/или терапија по **ID на термин** или по **име на пациент**. Ако терминот е сè уште `закажан`, статусот **автоматски** станува `завршен`.

```python
# backend/ai/lekar/zapishi_terapija.py (избор)
def _update_terapija(termin_id, dijagnoza, terapija, avtomatski_zavrshi) -> bool:
    delovi = []
    params: list = []
    if dijagnoza is not None:
        delovi.append("dijagnoza = %s"); params.append(dijagnoza)
    if terapija is not None:
        delovi.append("terapija = %s");  params.append(terapija)
    if avtomatski_zavrshi:
        delovi.append("status_pregled = 'завршен'")  # авто-завршување
    sql = "UPDATE Termin_pregled SET " + ", ".join(delovi) + " WHERE termin_ID = %s"
    params.append(termin_id)
    cur.execute(sql, tuple(params)); conn.commit()
    return True
```

> Ако има повеќе термини со ист пациент без запис, асистентот бара експлицитен ID — за да не запише на погрешен термин.

### Реален излез

```text
Записот е сочуван!

Пациент: Марко Иванов
Термин: ID 42 – 17.06.2026 09:30
Дијагноза: грип
Терапија: 2x дневно парацетамол

Статусот на терминот е автоматски променет на „завршен".
```

***

## 5. Пробај <a id="5-probaj"></a>

**Медицински картон** преку `POST /ai-chat/ask`:

```json
{
  "prasanje": "Дај ми картон на Петар Иванов",
  "lekar": { "doctor_ID": 28, "name": "Александар", "surname": "Серафимов" },
  "kontekst": null
}
```

**Запиши терапија**:

```json
{
  "prasanje": "Запиши терапија за Марко Иванов: 2x дневно парацетамол",
  "lekar": { "doctor_ID": 28, "name": "Александар", "surname": "Серафимов" },
  "kontekst": null
}
```

> `lekar.doctor_ID` мора да е валиден ID на лекар, инаку `require_lekar` го одбива барањето.

> **Тестирај го овде →** [POST `/ai-chat/ask`](../../../api/ai-chat.md#3-ask)

***

Следно: [Статистика](statistika.md) · [Распоред](raspored.md) · [Лекар (преглед)](../lekar.md)
