"""Partner-side signing helpers for the sanity suite.

The canonicalisation here MUST byte-for-byte match the Consent Manager's
(`utils/canonical.py`): stable key order, compact separators. The sanity acts as
a partner — it generates its own keypair, signs a consent object, and the CM
verifies it with the public key the suite onboards.
"""
import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def new_keypair():
    """Return (private_key, public_key_pem) for a fresh Ed25519 key."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pem


def load_private_key_pem(pem: str):
    """Load a PEM private key (Ed25519 / EC / RSA) — the partner's signing key,
    seeded in Partner Management, that the e2e signs with."""
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def sign_object(obj_without_signature: dict, priv, kid: str, algorithm: str = "EdDSA") -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding

    msg = canonical_bytes(obj_without_signature)
    if algorithm == "EdDSA":
        sig = priv.sign(msg)
    elif algorithm == "ES256":
        sig = priv.sign(msg, ec.ECDSA(hashes.SHA256()))
    elif algorithm == "RS256":
        sig = priv.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    else:
        raise ValueError(f"unsupported signing algorithm: {algorithm!r}")
    return {"algorithm": algorithm, "kid": kid, "value": b64url_encode(sig)}


def _public_key_from_jwk(jwk: dict):
    """Build a cryptography public key from a JWK (OKP / EC / RSA)."""
    kty = jwk.get("kty")
    if kty == "OKP":
        return ed25519.Ed25519PublicKey.from_public_bytes(b64url_decode(jwk["x"]))
    if kty == "EC":
        from cryptography.hazmat.primitives.asymmetric import ec
        x = int.from_bytes(b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(b64url_decode(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    if kty == "RSA":
        from cryptography.hazmat.primitives.asymmetric import rsa
        n = int.from_bytes(b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(b64url_decode(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    raise ValueError(f"unsupported JWK kty: {kty!r}")


def verify_receipt_signature(
    jwks: dict, kid: str, algorithm: str, message: bytes, signature_b64url: str
) -> bool:
    """Verify a CM receipt signature against the CM's published JWK by `kid`.

    Handles every key type the CM can sign with (EdDSA / ES256 / RS256), so the
    check works regardless of which .p12 the deployment uses — not just the demo
    (Ed25519) key.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding

    for jwk in jwks.get("keys", []):
        if jwk.get("kid") != kid:
            continue
        try:
            pub = _public_key_from_jwk(jwk)
            sig = b64url_decode(signature_b64url)
            if algorithm == "EdDSA":
                pub.verify(sig, message)
            elif algorithm == "ES256":
                pub.verify(sig, message, ec.ECDSA(hashes.SHA256()))
            elif algorithm == "RS256":
                pub.verify(sig, message, padding.PKCS1v15(), hashes.SHA256())
            else:
                return False
            return True
        except Exception:
            return False
    return False
