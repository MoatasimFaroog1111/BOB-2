import base64
import hashlib
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.core.config import settings

# Use a constant salt - in production, this should be stored securely and separately
# from the database. For now, we derive it deterministically from SECRET_KEY.
SALT_HASH = hashlib.sha256(b"guardianai_salt_" + settings.SECRET_KEY.encode()).digest()[:16]


def get_fernet_key() -> bytes:
    """
    Derive a secure Fernet key from SECRET_KEY using PBKDF2.
    This is more secure than simple SHA256 hashing.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT_HASH,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.SECRET_KEY.encode()))
    return key


def encrypt_value(value: str) -> str:
    """Encrypt a string value using Fernet symmetric encryption."""
    if not value:
        return ""
    try:
        f = Fernet(get_fernet_key())
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        # Log error but don't expose details
        raise ValueError("Encryption failed") from e


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a Fernet-encrypted string value."""
    if not encrypted_value:
        return ""
    try:
        f = Fernet(get_fernet_key())
        return f.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        # Log error but don't expose details
        raise ValueError("Decryption failed - invalid or corrupted data") from e


def rotate_encryption_key(old_secret_key: str, new_secret_key: str, encrypted_data: str) -> str:
    """
    Re-encrypt data with a new key (key rotation).
    This allows changing SECRET_KEY without losing encrypted data.
    """
    # Temporarily use old key to decrypt
    old_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT_HASH,
        iterations=100000,
    )
    old_key = base64.urlsafe_b64encode(old_kdf.derive(old_secret_key.encode()))

    new_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT_HASH,
        iterations=100000,
    )
    new_key = base64.urlsafe_b64encode(new_kdf.derive(new_secret_key.encode()))

    # Decrypt with old key
    f_old = Fernet(old_key)
    decrypted = f_old.decrypt(encrypted_data.encode())

    # Re-encrypt with new key
    f_new = Fernet(new_key)
    return f_new.encrypt(decrypted).decode()
