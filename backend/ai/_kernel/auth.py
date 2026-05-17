"""Проверки на улога за AI handler-и — централизирано и конзистентно."""

MSG_PACIENT = "За оваа акција треба да се најавиш како пациент."
MSG_LEKAR = "Мораш прво да се најавиш како лекар."
MSG_DIREKTOR = "Мораш прво да се најавиш како директор."
MSG_SAMO_DIREKTOR = "Само директорот може да ја изврши оваа акција."


def require_pacient(pacient: dict | None, *, poraka: str | None = None) -> str | None:
    """Враќа текст на грешка ако нема логиран пациент со email, инаку None."""
    if pacient and pacient.get("email"):
        return None
    return poraka or MSG_PACIENT


def require_lekar(lekar: dict | None, *, poraka: str | None = None) -> str | None:
    if lekar and lekar.get("doctor_ID"):
        return None
    return poraka or MSG_LEKAR


def require_direktor(lekar: dict | None, *, poraka: str | None = None) -> str | None:
    """Лекар + check_admin_access (директор на болницата — исто како таб Администрација)."""
    if not lekar or not lekar.get("doctor_ID"):
        return (
            poraka
            or "За објава вест на сајтот треба да сте најавени како лекар (директор).\n\n"
            "Најавете се преку „Најава за лекари“ — гостинскиот режим не може да објавува вести."
        )
    from routers.admin import check_admin_access

    try:
        doctor_id = int(lekar["doctor_ID"])  # type: ignore[index]
    except (TypeError, ValueError):
        return poraka or MSG_DIREKTOR
    if not check_admin_access(doctor_id):
        ime = f"{lekar.get('name', '')} {lekar.get('surname', '')}".strip() or "лекар"
        return (
            "Објавување вести преку асистентот е достапно само за "
            "директорот на болницата (исто како табот „Администрација“ на сајтот).\n\n"
            f"Вие сте најавени како д-р {ime}.\n\n"
            "Ако сте директор, најавете се со профилот на д-р Владко Захариев. "
            "Инаку вестите ги додава директорот преку администрација или делот Новости."
        )
    return None
