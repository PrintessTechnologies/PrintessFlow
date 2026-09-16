# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# The PrintessFlow license code: what one looks like, how one is minted, and
# how the app checks one. This file is the single definition of the format.
# The plugin imports it to verify, and make_license.py (in OneDrive\Python
# Automation\PrintessFlowLicensing, outside the repo) imports it to mint, so
# the two cannot disagree.
#
# A code is an Ed25519 signature over a license number:
#
#     PF1-<NUMBER>-<signature, base32, no padding>
#
# The app carries only the PUBLIC key, so nothing shipped to a user lets anyone
# mint a code; the private key stays on Alex's computer, outside the repo. A
# code minted next year verifies against every build already out there, and
# there is no list of codes to run out of: the number IS the code's identity.
#
# The number is inside the code in the clear so the app can say which license
# it was activated with. Numbers are usually plain digits (0001, 0002, ...)
# but may be any letters, digits and dashes, a printer serial for instance;
# the signature never contains a dash (base32 is letters and digits), so the
# code is split on its LAST dash.
#
# Verification uses the `cryptography` package that ships inside PrintessFlow
# (it is in Cura's own requirements), and falls back to a small pure-Python
# Ed25519 verifier if that import ever fails, so a packaging change on one
# platform cannot quietly turn the gate off. The fallback is the RFC 8032
# reference algorithm; it is slow (about a tenth of a second) but runs once.

import base64
import hashlib
import re
from typing import Optional, Tuple

CODE_PREFIX = "PF1"

# Domain separation: the bytes signed are not the bare number, so a signature
# made for anything else Printess might ever sign can never double as a code.
SIGNED_CONTEXT = b"PrintessFlow license v1\n"

# Ed25519 public key, hex. The matching private key is NOT in the repo.
PUBLIC_KEY_HEX = "861f6f2bd8e7d461fe8fabc8ef660e4853881c36dcb9c99f8e95aeeea2d785ce"

_NUMBER_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,30}[A-Z0-9]$")


class LicenseError(ValueError):
    """A code that cannot be accepted, with a message fit to show the user."""


# ----------------------------------------------------------------------
# Format
# ----------------------------------------------------------------------

def normalize_number(number: str) -> str:
    """The license number as it appears in a code: upper case, no spaces."""
    s = "".join(str(number).split()).upper()
    if not _NUMBER_RE.match(s):
        raise LicenseError("The license number must be 3 to 32 letters, digits or dashes.")
    return s


def signed_message(number: str) -> bytes:
    return SIGNED_CONTEXT + normalize_number(number).encode("ascii")


def format_code(number: str, signature: bytes) -> str:
    sig = base64.b32encode(signature).decode("ascii").rstrip("=")
    return "%s-%s-%s" % (CODE_PREFIX, normalize_number(number), sig)


def parse_code(code: str) -> Tuple[str, bytes]:
    """Split a pasted code into (number, signature). Tolerates line breaks and
    surrounding whitespace, which an emailed code picks up on the way."""
    text = "".join(code.split()).upper()
    if not text:
        raise LicenseError("Enter the activation code that came with your printer.")
    if not text.startswith(CODE_PREFIX + "-"):
        raise LicenseError("This is not a PrintessFlow activation code.")
    body = text[len(CODE_PREFIX) + 1:]
    if "-" not in body:
        raise LicenseError("The code is incomplete. Copy the whole line, including the part after the last dash.")
    number, sig_text = body.rsplit("-", 1)
    try:
        number = normalize_number(number)
    except LicenseError:
        raise LicenseError("The code is not in the expected form.")
    pad = "=" * (-len(sig_text) % 8)
    try:
        signature = base64.b32decode(sig_text + pad)
    except Exception:
        signature = b""
    if len(signature) != 64:
        raise LicenseError("The code is incomplete or has been altered. Copy the whole line exactly as it was sent.")
    return number, signature


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------

def verify_code(code: str, public_key_hex: str = PUBLIC_KEY_HEX) -> str:
    """The license number the code was issued for. Raises LicenseError otherwise."""
    number, signature = parse_code(code)
    if not _verify(bytes.fromhex(public_key_hex), signed_message(number), signature):
        raise LicenseError("This code is not valid. Check it against the one you were sent, "
                           "or contact contact@printesstechnologies.com.")
    return number


def _verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return _ed25519_verify_pure(public_key, message, signature)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except InvalidSignature:
        return False
    except ValueError:
        return False


# ----------------------------------------------------------------------
# Minting (only make_license.py calls this; the app never has the key)
# ----------------------------------------------------------------------

def make_code(private_key_seed: bytes, number: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(private_key_seed)
    return format_code(number, key.sign(signed_message(number)))


def public_key_hex_for(private_key_seed: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.from_private_bytes(private_key_seed)
    return key.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw).hex()


# ----------------------------------------------------------------------
# Pure-Python Ed25519 verify (RFC 8032 reference algorithm), fallback only
# ----------------------------------------------------------------------

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = (-121665 * _inv(121666)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * _inv(5)) % _P
_B = (_xrecover(_BY), _BY)


def _edwards(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[int, int]:
    x1, y1 = a
    x2, y2 = b
    k = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + k)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - k)
    return (x3 % _P, y3 % _P)


def _scalarmult(point: Tuple[int, int], e: int) -> Tuple[int, int]:
    result = (0, 1)
    while e:
        if e & 1:
            result = _edwards(result, point)
        point = _edwards(point, point)
        e >>= 1
    return result


def _decodepoint(s: bytes) -> Optional[Tuple[int, int]]:
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P != 0:
        return None
    return (x, y)


def _ed25519_verify_pure(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64 or len(public_key) != 32:
        return False
    r = _decodepoint(signature[:32])
    a = _decodepoint(public_key)
    if r is None or a is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little")
    return _scalarmult(_B, s) == _edwards(r, _scalarmult(a, h))
