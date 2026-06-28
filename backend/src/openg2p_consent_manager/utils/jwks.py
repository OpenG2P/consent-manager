import json

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import ECAlgorithm, OKPAlgorithm, RSAAlgorithm

# Default JWS algorithm per key type, when the JWK omits "alg".
_DEFAULT_ALG = {"OKP": "EdDSA", "EC": "ES256", "RSA": "RS256"}


def jwk_to_pem_and_alg(jwk: dict) -> tuple[str, str]:
    """Convert a public JWK into (PEM, algorithm).

    Uses PyJWT's algorithm classes to parse the JWK into a cryptography public
    key, then serialises it to PEM so it plugs into the same verify path as a
    stored PEM key. Raises ValueError for unsupported key types.
    """
    kty = jwk.get("kty")
    raw = json.dumps(jwk)
    if kty == "EC":
        key = ECAlgorithm.from_jwk(raw)
    elif kty == "RSA":
        key = RSAAlgorithm.from_jwk(raw)
    elif kty == "OKP":
        key = OKPAlgorithm.from_jwk(raw)
    else:
        raise ValueError(f"Unsupported JWK kty: {kty!r}")
    pem = key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    alg = jwk.get("alg") or _DEFAULT_ALG.get(kty, "")
    return pem, alg
