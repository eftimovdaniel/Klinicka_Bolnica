"""
AI пакет за Клиничка Болница Штип.

Структура (по улога на корисник):
- _kernel/   - инфраструктура (Groq клиент, intent детектори, prompts)
- pacient/   - AI функции за пациент
- lekar/     - AI функции за лекар
- direktor/  - AI функции за директор
- opsto/     - AI функции достапни на сите

Овој __init__.py ги re-експортира сите модули на ниво на пакетот,
така што постојниот код може да продолжи да пишува:
    from ai import zakazi_termin
без да знае во која подпапка живее модулот.
"""

# === KERNEL ===
from ai._kernel import groq_client, intent_detector, ai_intent_detector  # noqa: F401
from ai._kernel import transliteracija, prompts  # noqa: F401
from ai._kernel import ai_json, auth, db_helpers, prompt_helpers, handlers  # noqa: F401

# === PACIENT ===
from ai.pacient import slobodni_termini, zakazi_termin, otkazi_termin  # noqa: F401
from ai.pacient import prenesi_termin, postavi_potsetnik  # noqa: F401
from ai.pacient import oceni_pregled, trgni_ocena  # noqa: F401
from ai.pacient import moi_pregledi, apliciraj_za_rabota  # noqa: F401

# === LEKAR ===
from ai.lekar import zavrshi_pregled, istorija_pacient, karton_pacient  # noqa: F401
from ai.lekar import moj_raspored, moja_statistika, zapishi_terapija  # noqa: F401

# === DIREKTOR ===
from ai.direktor import kreiraj_oglas, zatvori_oglas, izbrisi_vest_oglas  # noqa: F401
from ai.direktor import aplikanti_oglas, promeni_dezurstvo  # noqa: F401
from ai.direktor import statistika_oddeli, objavi_vest  # noqa: F401
from ai.direktor import izvestaj_den_nedela  # noqa: F401

# === OPSTO ===
from ai.opsto import info_lekar, lekari_oddel, uslugi, navigacija  # noqa: F401
from ai.opsto import bolnica_info, preporaka_lekar  # noqa: F401
from ai.opsto import novosti_rezime, faq_pregled  # noqa: F401
