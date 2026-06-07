"""Order secrecy via PyNaCl SealedBox.

Diplomacy is simultaneous: no player may see another's orders before they
resolve. On a shared git branch that secrecy must be enforced by crypto, not
by asking agents not to peek.

Each match has one ADJUDICATOR keypair. The public key is committed to the
game branch; every power encrypts its orders to it with a SealedBox (anonymous
public-key encryption — anyone with the public key can encrypt, only the
private key can decrypt). The private key lives ONLY in a GitHub Actions repo
secret, so the adjudication workflow is the sole entity that can read pending
orders. After processing, the orders are revealed publicly in history/.
"""
from __future__ import annotations

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey, PublicKey, SealedBox


def generate_keypair() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) for a new adjudicator."""
    private = PrivateKey.generate()
    priv_b64 = private.encode(Base64Encoder).decode("ascii")
    pub_b64 = private.public_key.encode(Base64Encoder).decode("ascii")
    return priv_b64, pub_b64


def encrypt(public_key_b64: str, plaintext: str) -> str:
    """Seal `plaintext` to the public key; returns base64 ciphertext."""
    public_key = PublicKey(public_key_b64.strip().encode("ascii"), Base64Encoder)
    sealed = SealedBox(public_key).encrypt(plaintext.encode("utf-8"))
    return Base64Encoder.encode(sealed).decode("ascii")


def decrypt(private_key_b64: str, ciphertext_b64: str) -> str:
    """Open base64 ciphertext with the private key; returns plaintext."""
    private_key = PrivateKey(private_key_b64.strip().encode("ascii"), Base64Encoder)
    sealed = Base64Encoder.decode(ciphertext_b64.strip().encode("ascii"))
    return SealedBox(private_key).decrypt(sealed).decode("utf-8")
