"""The match spec — every lever a programmatic conductor run can pull.

`run_match` translates a plain-language match description ("give France a
cautious persona, 3 talk rounds, two Qwens in parallel") into edits on a
`MatchSpec`, then runs it. So this module's only job is to make every knob
explicit, orthogonal, and reachable both from a YAML file and from CLI flags.

    spec = MatchSpec.load("matches/frostbite.yaml", name="frostbite", press="full")
    print(spec.to_yaml())            # the fully-resolved plan

Nothing here runs a game or talks to a model — it just resolves configuration
(including the LM Studio endpoint for `local` seats) into a frozen plan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import yaml

from orchestration._common import POWERS

DEFAULT_MODEL = "qwen/qwen3.6-35b-a3b"
DEFAULT_LM_HOST = "http://localhost:1234"
DEFAULT_LM_TOKEN = "lmstudio"
# Reference LM Studio connection file (shared with setup_lm_studio/ask-local).
DEFAULT_LM_ENV = "~/agentic_work/setup_lm_studio/lmstudio.env"


def resolve_lm_studio(env_file: str | None = None) -> tuple[str, str]:
    """Resolve the LM Studio (base_url, token) for `local` seats.

    Precedence: explicit process env (LM_STUDIO_HOST / LM_API_TOKEN) >
    the lmstudio.env file (default: setup_lm_studio/lmstudio.env) > built-in
    localhost defaults. Missing file is fine — we fall back silently.
    """
    host, token = DEFAULT_LM_HOST, DEFAULT_LM_TOKEN
    path = Path(env_file or os.environ.get("LM_STUDIO_ENV") or DEFAULT_LM_ENV).expanduser()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key == "LM_STUDIO_HOST" and val:
                host = val
            elif key == "LM_API_TOKEN" and val:
                token = val
    # A real process-env override wins over the file.
    host = os.environ.get("LM_STUDIO_HOST", host)
    token = os.environ.get("LM_API_TOKEN", token)
    return host, token


@dataclass
class SeatSpec:
    """Per-power overrides. Anything left None inherits the match default."""
    model: str = DEFAULT_MODEL
    endpoint: str = "local"          # local (LM Studio) | api (Anthropic/subscription)
    base_url: str | None = None      # resolved for local seats
    token: str | None = None         # resolved for local seats
    persona: str | None = None       # free-text system flavor for this seat
    enabled: bool = True

    @property
    def idle(self) -> bool:
        return not self.enabled


@dataclass
class MatchSpec:
    """A fully-resolved, runnable match description."""
    name: str = "match"
    press: str = "none"                     # none | full
    idle: list[str] = field(default_factory=list)
    human: list[str] = field(default_factory=list)
    seats: dict[str, SeatSpec] = field(default_factory=dict)

    # Defaults applied to every seat that doesn't override them.
    model: str = DEFAULT_MODEL
    endpoint: str = "local"
    lm_studio_env: str | None = None

    negotiation_rounds: int = 0             # full-press, movement phases only
    session_mode: str = "oneshot"           # oneshot | persistent
    max_concurrency: int = 1
    max_phases: int = 20
    adjudication: str = "local"             # local (held key) | ci (push -> Actions)
    deadline: str = "wait"                  # wait | force
    seed_openings: bool = True

    per_call_timeout_s: float = 600.0
    retries: int = 1
    runs_dir: str = "runs"
    verbosity: int = 1
    dry_run: bool = False

    deadline_hours: float = 24.0

    # ------------------------------------------------------------------ #
    # Construction / loading
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | os.PathLike | None = None, **overrides) -> "MatchSpec":
        """Load from YAML (optional), apply overrides, then resolve.

        `overrides` are the CLI flags; only non-None values are applied so a
        flag left unset never clobbers a YAML value.
        """
        data: dict = {}
        if path:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path}: top-level YAML must be a mapping.")
            data = raw

        # Pull seats out separately — they need SeatSpec construction.
        raw_seats = data.pop("seats", {}) or {}

        spec_field_names = {f.name for f in fields(cls) if f.name != "seats"}
        kwargs = {k: v for k, v in data.items() if k in spec_field_names}
        unknown = set(data) - spec_field_names
        if unknown:
            raise ValueError(f"Unknown spec keys: {', '.join(sorted(unknown))}")

        # CLI overrides (skip None so unset flags don't clobber the YAML).
        seat_overrides = overrides.pop("seats", None)
        for k, v in overrides.items():
            if v is None:
                continue
            if k not in spec_field_names:
                raise ValueError(f"Unknown override: {k}")
            kwargs[k] = v

        spec = cls(**kwargs)
        spec._build_seats(raw_seats, seat_overrides or {})
        spec._normalize()
        spec._resolve_seats()
        return spec

    def _build_seats(self, raw_seats: dict, seat_overrides: dict) -> None:
        seat_field_names = {f.name for f in fields(SeatSpec)}
        merged: dict[str, dict] = {}
        for power, cfg in raw_seats.items():
            merged[power.upper()] = dict(cfg or {})
        for power, cfg in (seat_overrides or {}).items():
            merged.setdefault(power.upper(), {}).update(cfg or {})

        self.seats = {}
        for power in POWERS:
            cfg = merged.get(power, {})
            unknown = set(cfg) - seat_field_names
            if unknown:
                raise ValueError(
                    f"seats.{power}: unknown keys {', '.join(sorted(unknown))}")
            self.seats[power] = SeatSpec(
                model=cfg.get("model", self.model),
                endpoint=cfg.get("endpoint", self.endpoint),
                base_url=cfg.get("base_url"),
                token=cfg.get("token"),
                persona=cfg.get("persona"),
                enabled=cfg.get("enabled", True),
            )

    def _normalize(self) -> None:
        self.idle = [p.upper() for p in self.idle]
        self.human = [p.upper() for p in self.human]
        if self.press not in ("none", "full"):
            raise ValueError(f"press must be none|full, got {self.press!r}")
        if self.session_mode not in ("oneshot", "persistent"):
            raise ValueError(f"session_mode must be oneshot|persistent, got {self.session_mode!r}")
        if self.adjudication not in ("local", "ci"):
            raise ValueError(f"adjudication must be local|ci, got {self.adjudication!r}")
        if self.deadline not in ("wait", "force"):
            raise ValueError(f"deadline must be wait|force, got {self.deadline!r}")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        for power, seat in self.seats.items():
            if seat.endpoint not in ("local", "api"):
                raise ValueError(
                    f"seats.{power}.endpoint must be local|api, got {seat.endpoint!r}")

    def _resolve_seats(self) -> None:
        """Fill in base_url/token for local seats; clear them for api seats."""
        host, token = resolve_lm_studio(self.lm_studio_env)
        for seat in self.seats.values():
            if seat.endpoint == "local":
                seat.base_url = seat.base_url or host
                seat.token = seat.token or token
            else:  # api seats use the ambient Anthropic credentials
                seat.base_url = None
                seat.token = None

    # ------------------------------------------------------------------ #
    # Derived views
    # ------------------------------------------------------------------ #
    def idle_powers(self) -> list[str]:
        """Explicitly idle powers + any disabled seats (they never play)."""
        out = set(self.idle)
        out |= {p for p, s in self.seats.items() if not s.enabled}
        return sorted(out)

    def live_powers(self) -> list[str]:
        idle = set(self.idle_powers())
        return [p for p in POWERS if p not in idle]

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        d = asdict(self)
        d["idle_resolved"] = self.idle_powers()
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=False)


__all__ = ["MatchSpec", "SeatSpec", "resolve_lm_studio", "DEFAULT_MODEL"]
