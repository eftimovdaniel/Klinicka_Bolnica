# AI модул — краток водич (почетник)

Ова **не** е еден голем AI „мозок“. Се работи за **правила + база**, а Groq (облачен AI) се користи само каде што треба.

## Како тече едно прашање (3 чекори)

```
Корисник пишува во чат
        ↓
1. ai_chat.py  —  нормализира текст (латиница → кирилица)
        ↓
2. intent_detector.py  —  „што сака?“ (закажи / откажи / info лекар …)
        ↓
3. handlers.py → еден handler фајл  —  чита/пишува MySQL, понекогаш Groq
        ↓
Одговор назад до frontend
```

**Ти треба да ги познаеш само 4 места:**

| Фајл | Улога |
|------|--------|
| `routers/ai_chat.py` | HTTP API (`POST /ai-chat/ask`) |
| `ai/_kernel/intent_detector.py` | Кој intent (клучни зборови, па Groq) |
| `ai/_kernel/handlers.py` | Табела intent → функција |
| `ai/pacient/*.py`, `ai/lekar/*.py`, … | Конкретна логика + SQL |

## AI-only режим (без keyword/локални fallback)

Од неодамна системот е **AI-first**:

- **Intent** → секогаш Groq (`detektiraj_intent_so_ai`)
- **Извлекување** (датум, лекар, …) → Groq JSON, без локално дополнување
- **Форматирање одговор** → Groq, без шаблон fallback

Потребен е **`GROQ_API_KEY`** во `backend/.env`. Ако Groq е исклучен (`GROQ_DISABLED=1`) или 429 → корисникот добива порака „Привремено сум преоптоварен…“, не локални правила.

```env
# GROQ_DISABLED=1   # НЕ користи за нормална работа — AI-only нема локален заменик
GROQ_API_KEY=gsk_...
```

По 429 (исцрпен лимит), ако `GROQ_AUTO_OFFLINE=1` (default), системот **сам** преминува на локално ~10 мин.

## Каде е најмногу код (не мора сè одеднаш)

| Фајл | ~лини | Зошто е голем |
|------|-------|----------------|
| `pacient/slobodni_termini.py` | 1700+ | датуми, лекари, слободни термини |
| `_kernel/intent_detector.py` | 1400+ | листи клучни зборови |
| `pacient/apliciraj_za_rabota.py` | 1400+ | апликации за работа |
| `pacient/zakazi_termin.py` | 1000+ | закажување |

За почетник: **не читај ги од почеток до крај**. Отвори го handler-от за intent што те интересира (на пр. `otkazi_termin.py` — ~400 лини).

## Заеднички помошници (`ai/_kernel/`)

- `utils.py` — `format_vreme`, `format_datum`, `format_datum_so_den`, `format_datum_vreme`, `format_datum_i_vreme`
- `groq_client.py` — единствен Groq повик
- `lekar_lookup.py` — наоѓање лекар по име
- `db_helpers.py` — повторливи SQL шаблони

## Како да додадеш нова функција (шаблон)

1. Нов handler во `ai/pacient/moj_handler.py` со `def odgovori_za_...(prasanje, pacient) -> str`
2. Регистрирај во `handlers.py` (`_build_handlers`)
3. Додај клучни зборови во `intent_detector.py`
4. Тест со `GROQ_DISABLED=1` и типични фрази

## Поедноставување во иднина (без да се скрши)

Може **фазно**, не цел систем одеднаш:

1. **Спој** `slobodni_termini` + `zakazi_termin` во помали модули (`datum.py`, `lekar.py`)
2. **Намали** `intent_detector` — помалку дуплирани keyword листи
3. **Еден патерн** за сите pacient handler-и: извлечи JSON (Groq или локално) → SQL → текст одговор
4. **Остави Groq** само за intent fallback и 2–3 тешки задачи (апликација за работа, слободни термини)

Види и `ai/_kernel/agent_guidelines.py` за официјалниот модел intent → handler → DB → AI.
