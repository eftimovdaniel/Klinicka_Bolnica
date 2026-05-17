"""Помошни функции за напомена на термин (приказ и системски текст)."""

NAPOMENA_SISTEM_AI = "Закажано преку AI асистент"


def napomena_za_prikaz_lekar(napomena: str | None) -> str | None:
    """Враќа текст за приказ кај лекар; системската AI напомена се крие."""
    if not napomena:
        return None
    t = str(napomena).strip()
    if not t:
        return None
    low = t.lower()
    if "закажано преку ai" in low:
        return None
    return t
