from __future__ import annotations
import logging
import threading
import time
from collections import defaultdict, deque
from bezbednost.postavki import REDIS_ADRESA

dnevnik = logging.getLogger(__name__)

class Ogranicuvac:
    def __init__(self, granica: int, prozorec_sekundi: float = 60.0) -> None:
        self.granica = granica
        self.prozorec = prozorec_sekundi
        self._pogodoci: dict[str, deque[float]] = defaultdict(deque)
        self._brava = threading.Lock()

    def dozvoleno(self, kluc: str) -> bool:
        sega = time.monotonic()
        with self._brava:
            zapisi = self._pogodoci[kluc]
            while zapisi and sega - zapisi[0] > self.prozorec:
                zapisi.popleft()
            if len(zapisi) >= self.granica:
                return False
            zapisi.append(sega)
            if len(self._pogodoci) > 10_000:
                prazni = [ime for ime, redica in self._pogodoci.items() if not redica]
                for ime in prazni:
                    del self._pogodoci[ime]
            return True


class RedisOgranicuvac:
    def __init__(self, adresa: str, granica: int, prozorec_sekundi: int = 60) -> None:
        import redis
        self.granica = granica
        self.prozorec = prozorec_sekundi
        self._redis = redis.Redis.from_url(adresa, decode_responses=True, socket_timeout=2)
        self._rezerva = Ogranicuvac(granica=granica, prozorec_sekundi=prozorec_sekundi)

    def dozvoleno(self, kluc: str) -> bool:
        try:
            redis_kluc = f"ogranicuvanje:{kluc}"
            cevka = self._redis.pipeline()
            cevka.incr(redis_kluc)
            cevka.expire(redis_kluc, self.prozorec, nx=True)
            brojac, _ = cevka.execute()
            return int(brojac) <= self.granica
        except Exception as greska:
            return self._rezerva.dozvoleno(kluc)


def napravi_ogranicuvac(granica: int):
    if REDIS_ADRESA:
        return RedisOgranicuvac(REDIS_ADRESA, granica=granica)
    return Ogranicuvac(granica=granica)
