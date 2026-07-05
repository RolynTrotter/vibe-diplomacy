"""Tournament harness: rotation, order-quality scoring, and the full loop.

The end-to-end test uses the fake backend (no model server) with one phase
per game — enough to prove each game gets its own directory/key, seats
rotate, and the aggregate JSON has the quality metrics.
"""
import json
from pathlib import Path

from orchestration._common import POWERS
from orchestration.match_spec import MatchSpec
from orchestration.run_tournament import (order_quality, rotated_seats,
                                          run_tournament, seat_key)

REPO = Path(__file__).resolve().parent.parent


def test_rotated_seats_shift_around_the_table():
    spec = MatchSpec.load(None, name="t", seats={
        "AUSTRIA": {"model": "m-aus"}, "ENGLAND": {"model": "m-eng"},
    })
    r1 = rotated_seats(spec.seats, 1)
    # Shift 1: each power inherits the seat of the NEXT power in POWERS order.
    assert r1["TURKEY"].model == "m-aus"        # TURKEY <- AUSTRIA's seat
    assert r1["AUSTRIA"].model == "m-eng"       # AUSTRIA <- ENGLAND's seat
    # Shift 7 == identity.
    r7 = rotated_seats(spec.seats, 7)
    assert all(r7[p] is spec.seats[p] for p in POWERS)


def test_order_quality_counts_from_history(tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "S1901M.json").write_text(json.dumps({
        "phase": "S1901M",
        "orders": {
            "FRANCE": [
                "A PAR S A MAR - BUR",     # void (see results)
                "A MAR - SPA",
                "F BRE - MAO",
            ],
            "ENGLAND": [
                "A LVP - WAL",
                "A YOR - WAL",             # self-bounce pair
                "F LON S A WAL - YOR",     # cross-dep? no — WAL is not England's
            ],
        },
        "results": {
            "A PAR": ["void"],
            "A MAR": [],
            "F BRE": ["bounce"],
            "A LVP": ["bounce"],
            "A YOR": ["bounce"],
            "F LON": ["void"],
        },
    }), encoding="utf-8")

    q = order_quality(tmp_path)
    fr, en = q["FRANCE"], q["ENGLAND"]
    assert fr["orders"] == 3 and fr["void"] == 1 and fr["bounce"] == 1
    assert fr["cross_deps"] == 0        # MAR is France's own ordered unit
    assert en["self_bounces"] == 2      # both movers to WAL count
    assert en["cross_deps"] == 1        # support of WAL, which England didn't order
    assert en["void"] == 1


def test_tournament_end_to_end_fake_backend(tmp_path):
    spec = MatchSpec.load(None, name="mini", max_phases=1, verbosity=0,
                          seats={"FRANCE": {"model": "marker-model"}})
    result = run_tournament(spec, games=2, rotate=True, backend="fake",
                            base_root=tmp_path, code_root=REPO)

    # Each game ran in its own root with its own artifacts.
    assert (tmp_path / "mini-g1" / "history" / "S1901M.json").exists()
    assert (tmp_path / "mini-g2" / "history" / "S1901M.json").exists()
    out = json.loads((tmp_path / "mini-tournament.json").read_text())
    assert len(out["games"]) == 2

    # Rotation: game 1 has the marker on FRANCE, game 2 on ENGLAND (the seat
    # map shifted by one, so ENGLAND inherits FRANCE's game-1 seat).
    g1, g2 = out["games"]
    assert g1["powers"]["FRANCE"]["seat"] == "marker-model"
    assert g2["powers"]["FRANCE"]["seat"] != "marker-model"
    assert g2["powers"]["ENGLAND"]["seat"] == "marker-model"

    # Quality metrics are present and sane on every record.
    for game in out["games"]:
        for rec in game["powers"].values():
            assert 0 <= rec["void_rate"] <= 1
            assert 0 <= rec["bounce_rate"] <= 1
            assert rec["orders"] > 0
    # And aggregated by seat identity across the rotation.
    assert out["by_seat"]["marker-model"]["games"] == 2
    assert set(out["by_power"]) == set(POWERS)


def test_seat_key_includes_persona():
    spec = MatchSpec.load(None, name="t", seats={
        "FRANCE": {"persona": "cautious and defensive"}})
    assert seat_key(spec.seats["FRANCE"]).endswith("| cautious and defensive")
    assert seat_key(spec.seats["ITALY"]) == spec.seats["ITALY"].model
