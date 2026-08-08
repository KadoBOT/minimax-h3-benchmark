"""Opaque, time-sortable run identifiers.

Lexicographic order equals creation order, so ``ORDER BY id`` is chronological without a
second index, and there is no arithmetic to collide the way the old
``run_003_model_cache_sol`` scheme did.
"""

from __future__ import annotations

import secrets
import threading
import time

# Crockford base32: no I, L, O, U — safe to read aloud and to paste.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_CHARS = 10  # 48 bits of milliseconds
_RANDOM_CHARS = 16  # 80 bits of entropy
ID_LENGTH = _TIME_CHARS + _RANDOM_CHARS

_lock = threading.Lock()
_last_ms = 0
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_id(now_ms: int | None = None) -> str:
    """A 26-character sortable id.

    Two ids created inside the same millisecond still sort in call order: the random
    component is incremented rather than redrawn, which is what makes a burst of enqueues
    keep its order.
    """
    global _last_ms, _last_random
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _lock:
        if stamp == _last_ms:
            _last_random += 1
            if _last_random >= 1 << (5 * _RANDOM_CHARS):
                stamp += 1
                _last_ms = stamp
                _last_random = secrets.randbits(5 * _RANDOM_CHARS - 8)
        else:
            _last_ms = stamp
            _last_random = secrets.randbits(5 * _RANDOM_CHARS - 8)
        randomness = _last_random
    return _encode(stamp, _TIME_CHARS) + _encode(randomness, _RANDOM_CHARS)


def is_valid_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) != ID_LENGTH:
        return False
    return all(char in _ALPHABET for char in value)
