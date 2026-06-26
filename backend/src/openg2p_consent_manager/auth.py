import logging
from typing import Dict

import jwt
from fastapi import Header, HTTPException, status

from .config import Settings

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


async def get_current_subject(
    authorization: str = Header(..., alias="Authorization"),
) -> Dict[str, str]:
    """Resolve the authenticated subject from a Bearer OIDC token.

    Verifies against the IdP JWKS when ``oidc_jwks_url`` is configured; otherwise
    decodes claims unverified (dev only). Every ``/my/*`` query is then scoped to
    this identity, so a subject can only ever see their own consents.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with 'Bearer '",
        )
    token = authorization[len("Bearer ") :]

    try:
        if _config.oidc_jwks_url:
            jwk_client = jwt.PyJWKClient(_config.oidc_jwks_url)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=_config.oidc_audience or None,
                issuer=_config.oidc_issuer or None,
                options={"verify_aud": bool(_config.oidc_audience)},
            )
        else:
            _logger.warning(
                "oidc_jwks_url not configured — subject token decoded WITHOUT "
                "signature verification (dev only)."
            )
            claims = jwt.decode(token, options={"verify_signature": False})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )

    subject_id_type = claims.get("subject_id_type")
    subject_id_value = claims.get("subject_id_value") or claims.get("sub")
    if not subject_id_type or not subject_id_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token must carry 'subject_id_type' and a subject identifier",
        )
    return {
        "subject_id_type": subject_id_type,
        "subject_id_value": subject_id_value,
    }
