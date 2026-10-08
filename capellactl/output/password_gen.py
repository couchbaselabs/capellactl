"""Generated passwords and Capella's password rules (CAP-028 AC2/AC3).

Rules (Management API spec, CreateDatabaseCredentialRequest.password): at least 8 characters with an upper-case
letter, a lower-case letter, a number and a special character, and none of `< > ; . * & | £`.
"""

from __future__ import annotations

import secrets
import string

FORBIDDEN = set("<>;.*&|£")
SPECIAL = "!@#$%^()-_=+[]{}:,?"  # no FORBIDDEN characters
RULES = "min 8, upper, lower, digit, special, none of < > ; . * & | £"
_CLASSES = (string.ascii_uppercase, string.ascii_lowercase, string.digits, SPECIAL)


def meets_rules(password: str) -> bool:
    return (len(password) >= 8 and any(c.isupper() for c in password) and any(c.islower() for c in password)
            and any(c.isdigit() for c in password) and any(not c.isalnum() for c in password)
            and not FORBIDDEN.intersection(password))


def generate_password(length: int = 32) -> str:
    """One character from each class, the rest from all of them, shuffled with a CSPRNG."""
    alphabet = "".join(_CLASSES)
    chars = [secrets.choice(cls) for cls in _CLASSES] + [secrets.choice(alphabet) for _ in range(length - len(_CLASSES))]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)
