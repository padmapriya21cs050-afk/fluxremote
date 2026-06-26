# fluxremote/backend/auth.py
import hashlib
import secrets

# Password hashing utilities for device credential protection

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2 with a random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256', 
        password.encode('utf-8'), 
        salt.encode('utf-8'), 
        100000
    )
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    """Verifies a password against its PBKDF2 hash."""
    try:
        parts = hashed_password.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        iterations = int(parts[1])
        salt = parts[2]
        stored_key_hex = parts[3]
        
        test_key = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            salt.encode('utf-8'), 
            iterations
        )
        return secrets.compare_digest(test_key.hex(), stored_key_hex)
    except Exception:
        return False

