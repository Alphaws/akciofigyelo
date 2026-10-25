import hashlib
import hmac
import os
import json
import base64
import time
from typing import Optional, Dict, Any
import httpx

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "akciofigyelo_super_secret_auth_token_key_2026")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        salt, key_hex = hashed.split("$", 1)
        check_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return hmac.compare_digest(check_key.hex(), key_hex)
    except Exception:
        return False

def create_access_token(user_id: int, email: str, name: str, role: str = "editor", expires_in: int = 86400 * 7) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "role": role,
        "exp": int(time.time()) + expires_in
    }
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(
        SECRET_KEY.encode(),
        f"{header_b64}.{payload_b64}".encode(),
        hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.{sig_b64}"

def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        
        # Verify signature
        expected_sig = hmac.new(
            SECRET_KEY.encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256
        ).digest()
        actual_sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        
        payload_json = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)).decode()
        payload = json.loads(payload_json)
        
        if payload.get("exp") and payload["exp"] < time.time():
            return None
        return payload
    except Exception:
        return None

async def verify_google_id_token(id_token: str) -> Optional[Dict[str, str]]:
    """
    Google ID token validálása közvetlenül a Google tokeninfo végpontján keresztül (biztonságos, nem igényel külső nehéz C-függőséget).
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
            if resp.status_code != 200:
                return None
            data = resp.json()

            # Ellenőrizzük az iss-t
            if data.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
                return None

            # Ha van beállítva GOOGLE_CLIENT_ID, ellenőrizzük az aud-ot is
            if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
                return None

            email = data.get("email")
            if not email or data.get("email_verified") not in [True, "true"]:
                return None

            name = data.get("name") or email.split("@")[0]
            avatar = data.get("picture") or ""
            return {
                "google_id": data.get("sub"),
                "email": email.lower(),
                "name": name,
                "avatar_url": avatar
            }
    except Exception as e:
        return None
