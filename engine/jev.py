"""Thin wrapper around TypeSafe's System One API (Jev).

Jev answers *typed* questions: you hand it state and a set of questions, and
every answer comes back as one of the options you supplied. Nothing here knows
about Diplomacy — `engine/orders_jev.py` builds the questions; this module only
resolves credentials and makes the call.

The API key is read, in precedence order:

  1. the `TYPESAFE_API_KEY` process environment variable
  2. a `TYPESAFE_API_KEY=...` line in `secrets.local` at the repo root
     (already gitignored, same posture as the adjudicator private key)

Like `engine/mapviz.py`, this degrades politely: `available()` reports whether a
call could be made at all, so callers can fall back instead of exploding.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "jev-latest"
ENV_VAR = "TYPESAFE_API_KEY"
SECRETS_FILE = "secrets.local"


def _key_from_file(root: Path) -> str | None:
    """Read TYPESAFE_API_KEY out of the gitignored secrets.local, if present."""
    path = root / SECRETS_FILE
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == ENV_VAR:
            return val.strip().strip('"').strip("'") or None
    return None


def resolve_api_key(root: Path | None = None) -> str | None:
    """The API key, or None. A real process env var always wins over the file.

    Falls back to this checkout's own root after the game root, so a scratch or
    out-of-tree game directory still finds the key. In live play the two are the
    same directory (the game is a branch of this repo).
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env
    candidates = []
    if root:
        candidates.append(Path(root))
    candidates += [Path.cwd(), Path(__file__).resolve().parent.parent]
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        key = _key_from_file(path)
        if key:
            return key
    return None


def available(root: Path | None = None) -> tuple[bool, str]:
    """(can we call Jev?, why not). Mirrors `mapviz.available()`."""
    try:
        import typesafe_sdk  # noqa: F401
    except Exception as exc:
        return False, (f"typesafe-sdk not importable ({type(exc).__name__}: {exc}) — "
                       "pip install typesafe-sdk")
    if not resolve_api_key(root):
        return False, (f"no {ENV_VAR} — export it, or put "
                       f"`{ENV_VAR}=...` in {SECRETS_FILE} at the repo root")
    return True, ""


def ask(state, questions, *, root: Path | None = None, model: str = DEFAULT_MODEL,
        timeout: float | None = 60.0):
    """Send one System One request. Returns the SDK's SystemOneResponse.

    Every question in `questions` is answered in the same request and the
    answers come back under the same keys. Questions in one request run in
    parallel and cannot see each other's answers — that is deliberate here; see
    the batch-first design in issue #36.
    """
    from typesafe_sdk import TypeSafeClient

    key = resolve_api_key(root)
    if not key:
        ok, why = available(root)
        raise RuntimeError(f"cannot call Jev: {why}")
    with TypeSafeClient(api_key=key, timeout=timeout) as client:
        return client.system_one(state=state, questions=questions, model=model)
