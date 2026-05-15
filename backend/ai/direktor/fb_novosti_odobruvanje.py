"""
Одобрување на Facebook постови за објава на сајтот — само директор.

Flow:
1) „Синхронизирај Facebook" / копче во админ → нови pending постови
2) AI: „Има нова објава од Facebook: [наслов]. Дали да ја објавам на сајтот?" → да/не
3) да → Novosti; не → skipped; следен pending ако има
"""

from __future__ import annotations

from ai._kernel.auth import require_direktor
from ai.pacient.apliciraj_za_rabota import _parse_da_ne
from ai._kernel.transliteracija import transliterijaj
from fb_sync import FbSyncError, get_first_pending, get_pending_by_id, publish_pending, skip_pending, sync_facebook_posts


INTENT = "fb_novosti_odobruvanje"


def _prasanje_e_sync(prashanje: str) -> bool:
    p = transliterijaj(prashanje).lower()
    return any(
        w in p
        for w in (
            "синхронизирај",
            "синхронизира",
            "sync",
            "освежи facebook",
            "повлечи од facebook",
            "земи од facebook",
            "нови постови",
            "нови од facebook",
            "facebook новости",
            "фејсбук",
            "fejsbuk",
        )
    )


def _format_pending_preview(row: dict) -> str:
    naslov = (row.get("naslov") or "").strip() or "—"
    sodrzina = (row.get("sodrzina") or "").strip()
    plain = sodrzina.replace("<p>", "").replace("</p>", "\n").replace("<br>", " ")
    plain = " ".join(plain.split())
    if len(plain) > 280:
        plain = plain[:277] + "..."
    extra = ""
    if row.get("slika_url"):
        extra = "\n(има слика)"
    if row.get("fb_permalink"):
        extra += f"\nFacebook: {row['fb_permalink']}"
    return f"{naslov}{extra}\n\n{plain}" if plain else f"{naslov}{extra}"


def _pocni_potvrda_flow(row: dict) -> dict:
    pid = row["id"]
    preview = _format_pending_preview(row)
    return {
        "odgovor": (
            "Има нова објава од Facebook што чека одобрување:\n\n"
            f"{preview}\n\n"
            'Дали да ја објавам на сајтот во делот „Новости"?\n'
            'Одговорете со „да" или „не".'
        ),
        "kontekst": {
            "intent": INTENT,
            "cekam": "potvrda",
            "pending_id": pid,
        },
    }


def _sync_odgovor() -> dict:
    try:
        res = sync_facebook_posts()
    except FbSyncError as e:
        return {"odgovor": str(e), "kontekst": None}
    added = res.get("added", 0)
    pending = res.get("pending_count", 0)
    note = res.get("note") or ""
    deferred = res.get("deferred") or 0
    extra = ""
    if deferred:
        extra = (
            f"\n(Уште {deferred} понови постови не се внесени во овој циклус — "
            "синхронизирајте повторно по одобрување.)"
        )
    if pending == 0:
        return {
            "odgovor": (
                f"Синхронизацијата заврши. Додадени нови постови: {added}.\n"
                f"{note}\n\n"
                "Нема објави што чекаат одобрување."
                f"{extra}"
            ),
            "kontekst": None,
        }
    first = get_first_pending()
    if not first:
        return {
            "odgovor": (
                f"Синхронизацијата заврши (+{added} нови). "
                "Проверете повторно — нема прв pending пост."
            ),
            "kontekst": None,
        }
    intro = (
        f"Синхронизацијата заврши. Додадени {added} нови постови (само во ред за одобрување).\n"
        f"{note}{extra}\n\n"
    )
    flow = _pocni_potvrda_flow(first)
    flow["odgovor"] = intro + flow["odgovor"]
    return flow


def _sleden_ili_kraj(admin_doctor_id: int, poraka: str) -> dict:
    nareden = get_first_pending()
    if not nareden:
        return {
            "odgovor": poraka + "\n\nНема повеќе објави што чекаат одобрување.",
            "kontekst": None,
        }
    flow = _pocni_potvrda_flow(nareden)
    flow["odgovor"] = poraka + "\n\n" + flow["odgovor"]
    return flow


def odgovori_za_fb_novosti(
    prashanje: str,
    lekar: dict | None,
    kontekst: dict | None,
) -> dict:
    if err := require_direktor(lekar):
        return {"odgovor": err, "kontekst": None}

    doctor_id = int(lekar.get("doctor_ID") or lekar.get("doctor_id") or 0)
    cekam = (kontekst or {}).get("cekam")
    pending_id = (kontekst or {}).get("pending_id")

    if _prasanje_e_sync(prashanje) and cekam != "potvrda":
        return _sync_odgovor()

    if cekam == "potvrda" and pending_id:
        odluka = _parse_da_ne(prashanje)
        row = get_pending_by_id(int(pending_id))
        if not row:
            nareden = get_first_pending()
            if nareden:
                return _pocni_potvrda_flow(nareden)
            return {
                "odgovor": "Таа објава веќе е обработена. Нема други што чекаат.",
                "kontekst": None,
            }
        if odluka is None:
            return {
                "odgovor": (
                    f'Не разбрав. За „{row.get("naslov", "")}" — '
                    'одговорете со „да" за објава на сајтот, или „не" за прескокнување.'
                ),
                "kontekst": kontekst,
            }
        if odluka == "ne":
            skip_pending(int(pending_id))
            return _sleden_ili_kraj(
                doctor_id,
                "Во ред, не ја објавивме на сајтот.",
            )
        try:
            novost_id = publish_pending(int(pending_id), doctor_id)
        except FbSyncError as e:
            return {"odgovor": str(e), "kontekst": None}
        except Exception as e:
            print(f"[fb_novosti] publish: {e}")
            return {
                "odgovor": "Се случи грешка при објавувањето. Обидете се повторно.",
                "kontekst": kontekst,
            }
        return _sleden_ili_kraj(
            doctor_id,
            f"Објавено на сајтот (новост #{novost_id}).",
        )

    first = get_first_pending()
    if first:
        return _pocni_potvrda_flow(first)

    return {
        "odgovor": (
            "Нема Facebook објави што чекаат одобрување.\n\n"
            "Напишете «Синхронизирај Facebook» или користете го копчето "
            "во админ панелот, таб Новости."
        ),
        "kontekst": None,
    }
