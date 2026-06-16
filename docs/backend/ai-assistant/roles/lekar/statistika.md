# Лекар: Статистика

Лекарот може да ги провери своите лични статистики преку разговор — број прегледи по статус, просечна оцена од пациенти, и топ пациенти по број на завршени прегледи. Сите бројки се само за најавениот лекар и можат да се ограничат на временски период.

> Поврзано: [Лекар (преглед)](README.md) · [Распоред](raspored.md) · [Картон и пациенти](pacienti.md) ·
> [API: Администрација → Статистики](../../../api/admin.md#5-statistika)

## Содржина

* [1. Преглед](#1-pregled)
* [2. Како работи (`moja_statistika`)](#2-kako)
* [3. Реален излез](#3-izlez)
* [4. Пробај](#4-probaj)

***

## 1. Преглед <a id="1-pregled"></a>

| Намера | Фајл | Дејство |
|--------|------|---------|
| `moja_statistika` | `moja_statistika.py` | Три `SELECT` упити: прегледи по статус, просечна оцена, топ пациенти |

Поддржани периоди (Groq ги извлекува): `denes`, `nedela` (7 дена), `mesec` (30 дена), `godina`, `site` (вкупно).

***

## 2. Како работи (`moja_statistika`) <a id="2-kako"></a>

Handler-от прави три одделни упити, сите филтрирани по `doctor_ID` и (опционално) по почетен датум:

```python
# 1) прегледи по статус
sql = "SELECT status_pregled, COUNT(*) AS broj FROM Termin_pregled WHERE doctor_ID = %s"
# + AND datum_pregled >= %s  (ако има период)
sql += " GROUP BY status_pregled"

# 2) просечна оцена од Pregled_feedback (JOIN со Termin_pregled)
sql2 = ("SELECT AVG(F.ocena) AS prosek, COUNT(*) AS broj_ocena"
        " FROM Pregled_feedback F JOIN Termin_pregled T ON T.termin_ID = F.termin_ID"
        " WHERE T.doctor_ID = %s")

# 3) топ 3 пациенти по број завршени прегледи
sql3 = ("SELECT ime_pacient, COUNT(*) AS bp FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'завршен'"
        " GROUP BY ime_pacient ORDER BY bp DESC LIMIT 3")
```

Просечната оцена се прикажува и со ѕвездички (`★`), заокружена на цел број.

***

## 3. Реален излез <a id="3-izlez"></a>

```text
Статистики за д-р Александар Серафимов (за последните 30 дена):

Прегледи: 24 вкупно
• Завршени: 18
• Закажани: 5
• Откажани: 1

Просечна оцена: 4.60 / 5  ★★★★★
Број на оцени: 12

Топ пациенти (по број на завршени прегледи):
1. Петар Иванов: 4
2. Марија Петрова: 3
3. Daniel Eftimov: 2
```

Ако лекарот сè уште нема оцени: `Просечна оцена: уште нема оцени.`

***

## 4. Пробај <a id="4-probaj"></a>

**Статистика за период** преку `POST /ai-chat/ask`:

```json
{
  "prasanje": "Колку прегледи имав овој месец?",
  "lekar": { "doctor_ID": 28, "name": "Александар", "surname": "Серафимов" },
  "kontekst": null
}
```

**Просечна оцена**:

```json
{
  "prasanje": "Каква ми е просечната оцена?",
  "lekar": { "doctor_ID": 28, "name": "Александар", "surname": "Серафимов" },
  "kontekst": null
}
```

> `lekar.doctor_ID` мора да е валиден ID на лекар, инаку `require_lekar` го одбива барањето.

{% openapi-operation spec="KlinickaBolnicaAPI" path="/ai-chat/ask" method="post" %}
[OpenAPI KlinickaBolnicaAPI](https://klinicka-bolnica-stip2026.onrender.com/openapi.json)
{% endopenapi-operation %}

***

Следно: [Распоред](raspored.md) · [Картон и пациенти](pacienti.md) · [Лекар (преглед)](README.md)
