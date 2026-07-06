from datetime import datetime, timedelta, UTC
from typing import Optional
from uuid import uuid4
import jwt
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica que el password coincida con el hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Genera hash del password"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crea un JWT token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "jti": str(uuid4()),
        }
    )
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Crea un refresh token con expiración más larga (7 días por defecto)"""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode.update(
        {
            "exp": expire,
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "type": "refresh",
            "jti": str(uuid4()),
        }
    )
    encoded_jwt = jwt.encode(to_encode, settings.refresh_secret_key, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Decodifica y valida un JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience="pricing-app-api",
            issuer="pricing-app",
        )
        return payload
    except PyJWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    """Decode and validate a refresh token, tolerating the key transition.

    Tries the dedicated refresh key first, then falls back to SECRET_KEY so a
    refresh token minted just before this change deployed (signed with the old
    SECRET_KEY) still validates — no forced mass logout during the migration
    window. Same algorithm/audience/issuer constraints as decode_token.

    Returns the payload on the first key that validates, or None if no key does.
    The SECRET_KEY fallback is scheduled for removal once all pre-deploy
    SECRET_KEY-signed refresh tokens have expired.
    """
    # ponytail: drop the settings.SECRET_KEY fallback below (validate against
    # refresh_secret_key only) once the migration window has closed — see the
    # matching marker on Settings.REFRESH_SECRET_KEY in config.py.
    # dict.fromkeys preserves order and de-duplicates: when REFRESH_SECRET_KEY
    # is unset, refresh_secret_key == SECRET_KEY, so we avoid decoding twice.
    for key in dict.fromkeys((settings.refresh_secret_key, settings.SECRET_KEY)):
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[settings.ALGORITHM],
                audience="pricing-app-api",
                issuer="pricing-app",
            )
        except PyJWTError:
            continue
    return None


def remaining_ttl_seconds(payload: dict) -> int:
    """Seconds until this token's `exp`, clamped to >= 0.

    `exp` is a Unix timestamp (int/float) after PyJWT decoding. Used to set the
    denylist key TTL so the revocation record auto-expires exactly when the
    token would have expired anyway (no cleanup job, no unbounded growth).
    """
    exp = payload.get("exp")
    if exp is None:
        return 0
    remaining = int(exp - datetime.now(UTC).timestamp())
    return max(remaining, 0)
