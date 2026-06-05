"""Authentication helpers for FormGuard AI.

This module provides helper functions for password validation, hashing,
and token generation. Eventually these can be refactored into a Flask
blueprint; for now they centralize auth-related utilities.
"""
import re
import secrets
from werkzeug.security import generate_password_hash, check_password_hash


def validate_password_strength(password: str) -> (bool, str):
    """Validate password strength and return (ok, message).

    Requirements (example): at least 8 chars, uppercase, number, special char.
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must include an uppercase letter.'
    if not re.search(r'[0-9]', password):
        return False, 'Password must include a number.'
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\"\\|,.<>\/?]', password):
        return False, 'Password must include a special character.'
    return True, 'Password looks strong.'


def hash_password(password: str) -> str:
    """Return a salted hash for the given password."""
    return generate_password_hash(password)


def verify_password(hash: str, password: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    return check_password_hash(hash, password)


def generate_reset_token() -> str:
    """Return a short URL-safe token for password resets."""
    return secrets.token_urlsafe(24)
