"""Full-press comms (Epic 5): self-claimed identities + a sealed mail pool.

Design goals for ephemeral, self-serve agents (no human passing keys around):

* **Self-claimed identities.** A power generates its own keypair, commits its
  PUBLIC key as `players/<POWER>.json`, and keeps the private key locally in the
  gitignored `secrets/<POWER>.privkey`. No human, no shared secrets.
* **One sealed mail pool.** Every message is written to `mail/<id>.enc` with a
  random id, sealed (PyNaCl SealedBox) to each recipient's public key — plus an
  archive copy sealed to the ADJUDICATOR key. Because nothing identifying is in
  the filename and readers trial-decrypt the whole pool, spectators can't even
  see the sender→recipient graph, not just the bodies.
* **Reveal at game end.** Only the adjudicator can open the archive copies, so at
  game end it decrypts them into `mail/revealed.json` for the public post-mortem.

A message payload is: {id, phase, sender, recipient, body, sent_at}.
"""
from __future__ import annotations

import json
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path

from engine import crypto, state

GLOBAL = "GLOBAL"  # recipient value for a broadcast


def list_players(root: Path) -> dict[str, str]:
    """Map of claimed power -> message (encryption) public key (base64)."""
    out: dict[str, str] = {}
    pdir = state.players_dir(root)
    if not pdir.exists():
        return out
    for path in sorted(pdir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("power") and data.get("pubkey"):
            out[data["power"].upper()] = data["pubkey"]
    return out


def player_identity(root: Path, power: str) -> dict | None:
    """The full committed identity for a power (pubkey + sign_pubkey), or None."""
    pfile = state.player_file(root, power)
    if not pfile.exists():
        return None
    return json.loads(pfile.read_text(encoding="utf-8"))


def sign_pubkey(root: Path, power: str) -> str | None:
    ident = player_identity(root, power)
    return ident.get("sign_pubkey") if ident else None


def claim_power(root: Path, power: str, label: str | None = None) -> str:
    """Generate this power's keypairs; write its public identity + local keys.

    A power gets two keypairs: an encryption key (SealedBox, for receiving
    messages) and a signing key (Ed25519, to authenticate its orders/messages).
    The caller commits `players/<POWER>.json` to claim the seat; both private
    keys stay in the gitignored secrets/ file.

    Returns the encryption public key.
    """
    power = power.upper()
    enc_priv, enc_pub = crypto.generate_keypair()
    sign_priv, sign_pub = crypto.generate_signing_keypair()

    pfile = state.player_file(root, power)
    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(json.dumps({
        "power": power,
        "pubkey": enc_pub,
        "sign_pubkey": sign_pub,
        "label": label or "",
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")

    kfile = state.player_privkey_file(root, power)
    kfile.parent.mkdir(parents=True, exist_ok=True)
    kfile.write_text(json.dumps({"enc": enc_priv, "sign": sign_priv}) + "\n",
                     encoding="utf-8")
    return enc_pub


def load_keys(root: Path, power: str) -> dict | None:
    """The local private keys {'enc':..., 'sign':...} for a power, or None."""
    kfile = state.player_privkey_file(root, power)
    if not kfile.exists():
        return None
    raw = kfile.read_text(encoding="utf-8").strip()
    try:
        keys = json.loads(raw)
        if isinstance(keys, dict) and "enc" in keys:
            return keys
    except json.JSONDecodeError:
        pass
    return {"enc": raw, "sign": None}  # legacy: bare encryption key


def load_privkey(root: Path, power: str) -> str | None:
    keys = load_keys(root, power)
    return keys["enc"] if keys else None


def _canonical(payload: dict) -> str:
    """Stable serialization for signing/verifying (excludes the signature)."""
    return json.dumps({k: v for k, v in payload.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":"))


def _signed(payload: dict, sign_priv: str | None) -> dict:
    if sign_priv:
        payload = {**payload, "sig": crypto.sign(sign_priv, _canonical(payload))}
    return payload


def send_message(
    root: Path,
    sender: str,
    recipients: list[str],
    body: str,
    phase: str,
    adjudicator_pubkey: str,
    sign_priv: str | None = None,
) -> list[Path]:
    """Seal one signed message to each recipient + an adjudicator archive copy.

    Returns the written file paths (the caller commits them).
    """
    sender = sender.upper()
    players = list_players(root)
    mail = state.mail_dir(root)
    mail.mkdir(parents=True, exist_ok=True)

    msg_id = _secrets.token_hex(8)
    sent_at = datetime.now(timezone.utc).isoformat()
    broadcast = any(r.upper() in (GLOBAL, "ALL") for r in recipients)
    targets = [p for p in players if p != sender] if broadcast \
        else [r.upper() for r in recipients]

    written: list[Path] = []
    for recipient in targets:
        pubkey = players.get(recipient)
        if not pubkey:
            continue  # unclaimed seat: nobody to read it
        payload = _signed({
            "id": msg_id, "phase": phase, "sender": sender,
            "recipient": GLOBAL if broadcast else recipient,
            "body": body, "sent_at": sent_at,
        }, sign_priv)
        written.append(_write_sealed(mail, pubkey, payload))

    # Archive copy the adjudicator can reveal at game end.
    archive = _signed({
        "id": msg_id, "phase": phase, "sender": sender,
        "recipient": GLOBAL if broadcast else (targets[0] if targets else ""),
        "recipients": targets, "body": body, "sent_at": sent_at,
    }, sign_priv)
    written.append(_write_sealed(mail, adjudicator_pubkey, archive))
    return written


def _write_sealed(mail: Path, pubkey: str, payload: dict) -> Path:
    path = mail / f"{_secrets.token_hex(12)}.enc"
    path.write_text(crypto.encrypt(pubkey, json.dumps(payload)) + "\n", encoding="utf-8")
    return path


def _verify_msg(root: Path, msg: dict) -> bool:
    """Whether msg's signature matches its sender's committed signing key."""
    sig = msg.get("sig")
    spub = sign_pubkey(root, msg.get("sender", ""))
    return bool(sig and spub and crypto.verify(spub, _canonical(msg), sig))


def _iter_mail(root: Path):
    mail = state.mail_dir(root)
    if not mail.exists():
        return
    for path in sorted(mail.glob("*.enc")):
        yield path.read_text(encoding="utf-8").strip()


def read_inbox(root: Path, power: str, privkey: str) -> list[dict]:
    """Every message sealed to `power`, trial-decrypted from the pool."""
    msgs = []
    for ct in _iter_mail(root):
        pt = crypto.try_decrypt(privkey, ct)
        if pt is None:
            continue
        try:
            msg = json.loads(pt)
        except json.JSONDecodeError:
            continue
        msg["verified"] = _verify_msg(root, msg)
        msgs.append(msg)
    msgs.sort(key=lambda m: (m.get("sent_at", ""), m.get("id", "")))
    return msgs


def reveal(root: Path, adjudicator_priv: str) -> list[dict]:
    """Decrypt the archive copies into a sorted, deduped plaintext list."""
    by_id: dict[str, dict] = {}
    for ct in _iter_mail(root):
        pt = crypto.try_decrypt(adjudicator_priv, ct)
        if pt is None:
            continue
        try:
            m = json.loads(pt)
        except json.JSONDecodeError:
            continue
        if m.get("id"):
            m["verified"] = _verify_msg(root, m)
            by_id[m["id"]] = m
    out = list(by_id.values())
    out.sort(key=lambda m: (m.get("sent_at", ""), m.get("id", "")))
    return out
