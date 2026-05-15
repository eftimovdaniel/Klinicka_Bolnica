"""
За backward compatibility — целата логика е во ai.direktor.kreiraj_oglas.

Користи: from ai import kreiraj_oglas  (веќе re-export од direktor во ai/__init__.py)
или директно: from ai.direktor import kreiraj_oglas
"""

from ai.direktor.kreiraj_oglas import odgovori_za_kreiranje_oglas

__all__ = ["odgovori_za_kreiranje_oglas"]
