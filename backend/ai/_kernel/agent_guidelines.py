"""
Водич за AI агентот на КБ Штип — како работи во код (не RAG за факти од база).

Патека на едно прашање (реален свет):

  1. ПЕРЦЕПЦИЈА — intent_detector / ai_intent_detector
     „Што сака корисникот?" → intent (на пр. lekari_oddel, zakazi_termin)

  2. РУТИРАЊЕ — handlers.dispatch(intent, ctx)
     Секој intent има една handler функција (def), не слободен chat.

  3. АГЕНТСКИ ЧЕКОР — handler-от:
     a) Правила / алијаси (брзо, детерминистички) — на пр. oddel_resolver, lekar_lookup
     b) База (извор на вистина) — SQL за лекари, термини, дежурства
     c) AI (само кога треба) — избор од затворена листа, не измислување факти

  4. ОДГОВОР — форматиран текст (+ navigacija / akcija / kontekst ако треба)

Што НЕ правиме:
  - AI не „знае" кои лекари постојат — ги чита од MySQL.
  - AI не смее слободно да го именува одделот; мора да избере од листа од база.
  - Документација / RAG — само за FAQ, општи текстови (faq_pregled, bolnica_info), не за листа лекари.

Каде се грешките најчесто:
  - Слободно извлекување на оддел → погрешен fuzzy match (ОРЛ, Хирургија vs Неврохирургија).
  - Податоци во база ≠ имиња на сајтот → усогласување specialty / Oddeli.

Нов код за оддели: ai._kernel.oddel_resolver

Промптови / правила за Groq: backend/data/agent_prompts.txt (еден фајл, секции @@@ име @@@)
"""

# Типови на извор за логирање / debug
# Determiniran rezultat od pravila (regex, lookup)
SOURCE_RULES = "rules"
# Najden preku alias (na pr. "ORL" -> "Otorinolaringologija")
SOURCE_ALIAS = "alias"
# AI izbral od zatvorena lista (ne slobodno generiranje)
SOURCE_AI_LIST = "ai_closed_list"
# Tochno sovpaganje vo bazata (bez fuzzy match)
SOURCE_EXACT = "exact_db"
