"""Помошни функции за напомена на термин (приказ и системски текст)."""

# Sistemska napomena - oznachuva deka terminot e zakazhan preku AI asistent
NAPOMENA_SISTEM_AI = "Закажано преку AI асистент"


def napomena_za_prikaz_lekar(napomena: str | None) -> str | None:
    """Враќа текст за приказ кај лекар; системската AI напомена се крие."""
    if not napomena:
        return None
    # Ako napomenata e prazna, nema shto da se prikazhe
    t = str(napomena).strip()
    if not t:
        return None
    # Pa proverka i posle strip
    low = t.lower()
    if "закажано преку ai" in low:
        return None
    # Sistemskata napomena se krie - lekarot ne treba da ja gleda
    return t
    # Korisnichka napomena se vrakja kako shto e
