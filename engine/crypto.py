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
from nacl.exceptions import BadSignatureError
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey


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


def try_decrypt(private_key_b64: str, ciphertext_b64: str) -> str | None:
    """Like decrypt, but return None instead of raising when the key doesn't fit.

    Used to trial-decrypt the shared mail pool: a reader opens only the messages
    sealed to their own key and silently skips the rest.
    """
    try:
        return decrypt(private_key_b64, ciphertext_b64)
    except Exception:
        return None


# --- Signing (Ed25519): authenticate WHO submitted orders / sent a message --- #
# Encryption (above) gives secrecy but not authenticity — a SealedBox hides the
# sender. Signing closes that gap: a power signs its orders with its private
# signing key, and the adjudicator verifies against the power's committed public
# signing key, so e.g. France cannot submit Germany's orders.
def generate_signing_keypair() -> tuple[str, str]:
    """Return (signing_private_b64, signing_public_b64)."""
    signing = SigningKey.generate()
    priv_b64 = signing.encode(Base64Encoder).decode("ascii")
    pub_b64 = signing.verify_key.encode(Base64Encoder).decode("ascii")
    return priv_b64, pub_b64


def sign(signing_private_b64: str, message: str) -> str:
    """Return a base64 detached signature of `message`."""
    signing = SigningKey(signing_private_b64.strip().encode("ascii"), Base64Encoder)
    sig = signing.sign(message.encode("utf-8")).signature
    return Base64Encoder.encode(sig).decode("ascii")


def verify(signing_public_b64: str, message: str, signature_b64: str) -> bool:
    """Whether `signature_b64` is a valid signature of `message` for the key."""
    try:
        verify_key = VerifyKey(signing_public_b64.strip().encode("ascii"), Base64Encoder)
        sig = Base64Encoder.decode(signature_b64.strip().encode("ascii"))
        verify_key.verify(message.encode("utf-8"), sig)
        return True
    except (BadSignatureError, Exception):
        return False
