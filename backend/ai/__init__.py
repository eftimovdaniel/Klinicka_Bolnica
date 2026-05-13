"""
AI пакет - сè што е поврзано со вештачка интелигенција (Groq / Llama 3.3).

Структура:
- groq_client.py      - Функција за повикување на Groq API (ask_ai)
- prompts.py          - Системски prompts (упатства за AI-то)
- intent_detector.py  - Хибриден keyword + AI детектор на интент
- ai_intent_detector.py - Само AI верзија на детекторот
- transliteracija.py  - Латиница → кирилица конверзија
- slobodni_termini.py - Барање слободни термини кај лекар
- zakazi_termin.py    - Закажување нов термин
- otkazi_termin.py    - Откажување на термин
- prenesi_termin.py   - Префрлање на термин
- postavi_potsetnik.py - Потсетник за термин
- oceni_pregled.py    - Оцена за завршен преглед
- trgni_ocena.py      - Бришење на оцена
- info_lekar.py       - Информации за лекар
- preporaka_lekar.py  - Препорака по симптом
- bolnica_info.py     - Статички инфо за болницата (работно време, локации, итн.)
"""
