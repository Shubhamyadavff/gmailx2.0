import hashlib
import os
import time
import jwt

SECRET_KEY = "gF7$kQ2!mX9pLvR4wZ8nT3jY6hB1cD5eA0sU"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

def hash_password(password: str) -> str:
    """Generates a secure PBKDF2 password hash."""
    salt = os.urandom(16)
    rounds = 100000
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
    return f"pbkdf2:sha256:{rounds}${salt.hex()}${key.hex()}"

def verify_password(stored_password_hash: str, password: str) -> bool:
    """Verifies a password against its stored PBKDF2 hash."""
    try:
        parts = stored_password_hash.split('$')
        if len(parts) != 3:
            return False
        algo_info, salt_hex, key_hex = parts
        salt = bytes.fromhex(salt_hex)
        rounds = int(algo_info.split(':')[-1])
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
        return key.hex() == key_hex
    except Exception:
        return False

def create_access_token(data: dict) -> str:
    """Creates a JWT access token that expires in 24 hours."""
    to_encode = data.copy()
    expire = time.time() + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    """Decodes a JWT access token, returning its payload if valid, otherwise None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None
