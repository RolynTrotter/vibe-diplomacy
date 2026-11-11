"""Compare bench arms for Haiku-as-France in the France vs Austria sandbox.

Each arm is a checkout (a worktree with the change applied) that ran
`bench.gunboat --as FRANCE --label fa-france-<arm>`. DIRs are relative to
this repo's root:
  .venv/bin/python bench/compare_arms.py base=. e1=../vd-e1 e2=../vd-e2
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # the repo root
CODE = r'''
import sys
from vibe.game import Match
from bench.gunboat import score
arm = sys.argv[1]
names = [f"bench-fa-france-{arm}-{i}" for i in (1, 2, 3)]
finals = []
for n in names:
    m = Match.open(n); g = m.load(); idle = phases = 0
    for ph, st in g.state_history.items():
        ph = str(ph)
        if ph.endswith("M") and st["units"].get("FRANCE"):
            os_ = (m.history(ph) or {}).get("orders", {}).get("FRANCE") or []
            phases += 1; idle += all(o.endswith(" H") or " S " in o for o in os_)
    finals.append(f"{len(g.powers['FRANCE'].centers)}-{len(g.powers['AUSTRIA'].centers)} ({idle}/{phases} idle)")
gains = []
for y in (1902, 1904, 1906):
    rows = [score(Match.open(n), y)["FRANCE"] for n in names]
    gains.append(f"{sum(r['gain'] for r in rows) / 3:+.2f}")
    if y == 1906:
        missed = sum(r["missed"] for r in rows) / max(1, sum(r["falls"] for r in rows))
print(f"| {arm} | " + " | ".join(gains) + f" | {missed:.2f} | " + ", ".join(finals) + " |")
'''
print("| arm | gain by 1902 | by 1904 | by 1906 | missed/Fall | finals France-Austria (France idle phases) |")
print("|---|---|---|---|---|---|")
for pair in sys.argv[1:]:
    arm, d = pair.split("=")
    root = HERE / d
    out = subprocess.run([str(root / ".venv/bin/python"), "-c", CODE, arm], cwd=root,
                         capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip()[-300:])
