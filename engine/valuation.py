"""What each province is worth to a power, from one question to Jev.

A Choice over every province on the board — "which is of most vital interest to
your plans this turn?" — and then we keep the whole distribution, not the pick.

The question is deliberately bounded to the turn and otherwise empty of
strategy. An earlier version asked which province "does the most to decide how
your game goes", which selects for pivotality rather than value: at S1903M it
rated Portugal 3/100 — an undefended neutral centre one move from a French
army, a free build — because nothing was happening there. Naming the cases we
want instead (take this, defend that) only trades one hard-coded policy for
another; bounding the horizon and leaving the judgment alone does not.
Because the probabilities sum to 1, each province's share is directly a percent
of the power's attention: Turkey at S1901M puts 53 on Bulgaria, 15 on the Black
Sea, 12 on Constantinople, and nothing at all on the other 65.

One request per power per phase, ~11.5k tokens, about $0.0005. The alternative —
a Score question per province — costs twice as much, rates a power's own home
centre top in six cases out of seven, and compresses everything it cares about
into the top quartile. This is the cheaper and the sharper of the two.

The distribution is deliberately sparse: only the provinces where something is
actually being decided get weight. That makes it a statement of goals, not a
dense value field, and it says nothing about defending a quiet home centre.
"""
from __future__ import annotations

from pathlib import Path

from diplomacy import Game

from engine import jev, orders_jev


def _describe(game: Game, prov: str, entry: dict, power: str,
              impassable: set[str]) -> str:
    """One option: the province and the board facts that bear on its worth."""
    bits = [entry["terrain"].lower()]
    if entry.get("supply_center"):
        bits.append("supply centre, " + ("unclaimed" if entry["owned_by"] == "neutral"
                    else f"held by {entry['owned_by']}"))
    if entry.get("unit"):
        bits.append(entry["unit"])
    return (f"{entry['name']} — {'; '.join(bits)}. "
            f"{orders_jev._adjacent_scs(game, prov, impassable, power)}")


def province_values(game: Game, power: str, *, root: Path | None = None,
                    state: dict | None = None, model: str = jev.DEFAULT_MODEL,
                    ask=None) -> dict[str, float]:
    """Province -> percent of this power's attention (0-100, summing to ~100).

    `ask` is injectable for tests; it defaults to `engine.jev.ask`.
    """
    from typesafe_sdk import Choice

    power = power.upper()
    state = state if state is not None else orders_jev.build_state(
        game, power, root=root)
    graph = state["board_graph"]
    impassable = {l.upper().split("/")[0] for l in game.map.locs
                  if game.map.area_type(l.upper().split("/")[0]) == "SHUT"}

    question = Choice(
        instructions=(f"You are {power}'s field marshal. Which province is of most "
                      f"vital interest to your plans this turn?"),
        criteria={p: _describe(game, p, e, power, impassable)
                  for p, e in graph.items()},
    )
    caller = ask or (lambda s, q: jev.ask(s, q, root=root, model=model))
    response = caller(state, {"most_important": question})
    answer = response.answers["most_important"]
    return {p: round(v * 100, 1) for p, v in (answer.probabilities or {}).items()}
