"""Epic 5: full-press comms, identity, and order authentication.

The headline security property: a power cannot submit another power's orders.
"""
import json

from orchestration import _common, run_adjudication, submit_orders  # noqa: F401
from orchestration._common import canonical_order_payload

from engine import comms, crypto, state


# --------------------------------------------------------------------------- #
# Signing primitives
# --------------------------------------------------------------------------- #
def test_sign_verify_roundtrip_and_tamper():
    priv, pub = crypto.generate_signing_keypair()
    sig = crypto.sign(priv, "A PAR - BUR")
    assert crypto.verify(pub, "A PAR - BUR", sig)
    assert not crypto.verify(pub, "A PAR - PIC", sig)        # tampered message
    _, other_pub = crypto.generate_signing_keypair()
    assert not crypto.verify(other_pub, "A PAR - BUR", sig)  # wrong key


# --------------------------------------------------------------------------- #
# Identity / claims
# --------------------------------------------------------------------------- #
def test_claim_power_writes_identity_and_keys(tmp_path):
    comms.claim_power(tmp_path, "FRANCE", label="bot")
    ident = comms.player_identity(tmp_path, "FRANCE")
    assert ident["power"] == "FRANCE"
    assert ident["pubkey"] and ident["sign_pubkey"]
    keys = comms.load_keys(tmp_path, "FRANCE")
    assert keys["enc"] and keys["sign"]
    assert "FRANCE" in comms.list_players(tmp_path)


# --------------------------------------------------------------------------- #
# Messaging
# --------------------------------------------------------------------------- #
def _adjudicator(tmp_path):
    priv, pub = crypto.generate_keypair()
    pf = state.pubkey_file(tmp_path)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(pub, encoding="utf-8")
    return priv, pub


def test_message_only_recipient_can_read(tmp_path):
    adj_priv, adj_pub = _adjudicator(tmp_path)
    for p in ("FRANCE", "ENGLAND", "GERMANY"):
        comms.claim_power(tmp_path, p)

    fr_keys = comms.load_keys(tmp_path, "FRANCE")
    comms.send_message(tmp_path, "FRANCE", ["ENGLAND"], "DMZ the Channel?",
                       "S1901M", adj_pub, sign_priv=fr_keys["sign"])

    eng = comms.read_inbox(tmp_path, "ENGLAND", comms.load_privkey(tmp_path, "ENGLAND"))
    assert len(eng) == 1
    assert eng[0]["body"] == "DMZ the Channel?"
    assert eng[0]["sender"] == "FRANCE"
    assert eng[0]["verified"] is True                      # signature checks out

    # A third party cannot read it.
    ger = comms.read_inbox(tmp_path, "GERMANY", comms.load_privkey(tmp_path, "GERMANY"))
    assert ger == []


def test_broadcast_reaches_all_others_and_reveal(tmp_path):
    adj_priv, adj_pub = _adjudicator(tmp_path)
    for p in ("FRANCE", "ENGLAND", "GERMANY"):
        comms.claim_power(tmp_path, p)
    fr_keys = comms.load_keys(tmp_path, "FRANCE")
    comms.send_message(tmp_path, "FRANCE", ["ALL"], "Stop Russia.",
                       "S1901M", adj_pub, sign_priv=fr_keys["sign"])

    for p in ("ENGLAND", "GERMANY"):
        inbox = comms.read_inbox(tmp_path, p, comms.load_privkey(tmp_path, p))
        assert [m["body"] for m in inbox] == ["Stop Russia."]

    # End-of-game reveal: adjudicator opens the archive copy.
    revealed = comms.reveal(tmp_path, adj_priv)
    assert len(revealed) == 1
    assert revealed[0]["sender"] == "FRANCE"
    assert revealed[0]["recipient"] == "GLOBAL"


# --------------------------------------------------------------------------- #
# Order authentication — the headline property
# --------------------------------------------------------------------------- #
def _sealed_order_file(tmp_path, power, phase, orders, sign_priv, adj_pub):
    sig = crypto.sign(sign_priv, canonical_order_payload(power, phase, orders))
    payload = json.dumps({"power": power, "phase": phase, "orders": orders, "sig": sig},
                         sort_keys=True)
    path = state.power_orders_file(tmp_path, power, phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(crypto.encrypt(adj_pub, payload), encoding="utf-8")


def test_legit_orders_accepted(tmp_path):
    adj_priv, adj_pub = _adjudicator(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    fr_sign = comms.load_keys(tmp_path, "FRANCE")["sign"]
    _sealed_order_file(tmp_path, "FRANCE", "S1901M", ["A PAR - BUR"], fr_sign, adj_pub)

    got = run_adjudication._read_sealed_orders(tmp_path, adj_priv, "S1901M", ["FRANCE"])
    assert got == {"FRANCE": ["A PAR - BUR"]}


def test_france_cannot_submit_germanys_orders(tmp_path):
    """France signs a file claiming to be GERMANY — must be rejected."""
    adj_priv, adj_pub = _adjudicator(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    comms.claim_power(tmp_path, "GERMANY")
    fr_sign = comms.load_keys(tmp_path, "FRANCE")["sign"]

    # France forges Germany's orders, signing with its OWN key.
    _sealed_order_file(tmp_path, "GERMANY", "S1901M", ["A MUN - BUR"], fr_sign, adj_pub)

    got = run_adjudication._read_sealed_orders(
        tmp_path, adj_priv, "S1901M", ["FRANCE", "GERMANY"])
    assert "GERMANY" not in got            # forged orders dropped


def test_garbage_order_file_does_not_crash(tmp_path):
    adj_priv, adj_pub = _adjudicator(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    path = state.power_orders_file(tmp_path, "FRANCE", "S1901M")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a valid sealed payload", encoding="utf-8")

    got = run_adjudication._read_sealed_orders(tmp_path, adj_priv, "S1901M", ["FRANCE"])
    assert got == {}                       # ignored, no exception


def test_unsigned_orders_rejected(tmp_path):
    adj_priv, adj_pub = _adjudicator(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    payload = json.dumps({"power": "FRANCE", "phase": "S1901M",
                          "orders": ["A PAR - BUR"]}, sort_keys=True)
    path = state.power_orders_file(tmp_path, "FRANCE", "S1901M")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(crypto.encrypt(adj_pub, payload), encoding="utf-8")

    got = run_adjudication._read_sealed_orders(tmp_path, adj_priv, "S1901M", ["FRANCE"])
    assert got == {}                       # no signature -> rejected
