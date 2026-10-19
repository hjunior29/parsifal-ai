"""
Encryption for secrets Parsifal has to send to other services (the Jev API key), so that they are not stored in
clear text. Parsifal's own API tokens are not here: they are hashed, since they never need to be read back.

The encryption key is derived from SECRET_KEY. Changing SECRET_KEY makes the stored secrets unreadable; they then
have to be saved again.
"""

import base64

from django.conf import settings

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class DecryptionError(Exception):
    pass


def _fernet():
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"parsifal", info=b"parsifal secrets v1").derive(
        settings.SECRET_KEY.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value):
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise DecryptionError("The secret cannot be decrypted (was SECRET_KEY changed?).")
