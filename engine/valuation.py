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
        instructions=(f"You are {power}'s field marshal. Which province is of "
                      f"interest to your plans this turn?"),
        criteria={p: _describe(game, p, e, power, impassable)
                  for p, e in graph.items()},
    )
    caller = ask or (lambda s, q: jev.ask(s, q, root=root, model=model))
    response = caller(state, {"most_important": question})
    answer = response.answers["most_important"]
    return {p: round(v * 100, 1) for p, v in (answer.probabilities or {}).items()}


def _reachable(game: Game, power: str) -> list[str]:
    """Provinces any of this power's units could actually be ordered into.

    The question set is bounded by the board, not by the number of agreements
    a power has made — which is what keeps this from being whack-a-mole. Six
    DMZs and one DMZ cost the same two requests.
    """
    from engine import coherence, validate

    out = set()
    for options in validate.legal_orders(game, power).values():
        for order in options:
            dest = coherence.parse_order(order).dest
            if dest:
                out.add(dest.split("/")[0])
    return sorted(out)


#: A province clears a constraint at this probability. The gap either side is
#: wide — see `province_constraints` — so the exact value is not delicate.
CONSTRAINT_THRESHOLD = 0.45


def province_constraints(game: Game, power: str, *, root: Path | None = None,
                         state: dict | None = None,
                         threshold: float = CONSTRAINT_THRESHOLD,
                         model: str = jev.DEFAULT_MODEL,
                         ask=None) -> tuple[set[str], set[str]]:
    """(provinces to stay out of, provinces promised to another power).

    A prohibition cannot be enforced by describing it. Told "DMZ in Black Sea",
    Turkey's fleet sailed in 3/3 with priorities at 0-100, 3/3 at 0-1, 3/3 with
    no valuation at all, and 3/3 when the directions were dressed up as binding
    orders from a head of state carrying `weight: 5000`. Emphasis is prose, and
    prose loses to the number printed on the option. So a constraint has to
    take the option away instead.

    An earlier version asked one `Choice` over the board and read its
    distribution as a set. That works for one prohibition and collapses beyond
    it: given six DMZs the mass split, `NOTHING_IS_OFF_LIMITS` won at 0.56, and
    it returned Burgundy alone. A pick-one primitive cannot answer a
    many-of-N question.

    So it is one `Noul` per reachable province instead — a yes/no whose answer
    is a probability — asked twice, because there are three states a province
    can be in and they need different handling:

      * **demilitarised** — nobody goes in, including anyone you would escort.
      * **promised to a friend** — you stay out, but supporting them in is
        exactly what you agreed to do.
      * **free**.

    Two narrow questions separate these cleanly where one broad question did
    not; asking them in one request blurred both, so they go separately.
    Measured, two passes, at S1901M and F1901M:

      six DMZs      keep_out 6/6 at 0.68-0.78, next province 0.30; gifts none
      "bounce in    keep_out none (0.27) - an agreement to ENTER is not a bar;
       Black Sea"   gifts none
      "England      keep_out none (0.22); gift BEL at 0.95, next 0.14
       takes BEL"
    """
    from typesafe_sdk import Noul

    power = power.upper()
    state = state if state is not None else orders_jev.build_state(
        game, power, root=root)
    names = orders_jev._names(game)
    provs = _reachable(game, power)
    caller = ask or (lambda s, q: jev.ask(s, q, root=root, model=model))

    def _bar(prov: str) -> Noul:
        nm = names.get(prov, prov)
        return Noul(
            instructions=(f"You are {power}. Do your own standing orders forbid "
                          f"moving a unit into {nm} this turn?"),
            criteria={"true": (f"Your orders put {nm} off limits — a DMZ, or "
                               f"ground you promised to leave alone."),
                      "false": (f"Your orders say nothing that stops you "
                                f"entering {nm} — or they tell you to go there. "
                                f"An order to take, attack or bounce in {nm} is "
                                f"an order to move into it, not a bar on it.")})

    def _gift(prov: str) -> Noul:
        nm = names.get(prov, prov)
        return Noul(
            instructions=(f"You are {power}. Do your standing orders say {nm} is "
                          f"for ANOTHER power to take this turn, rather than "
                          f"for you?"),
            criteria={"true": (f"Your orders give {nm} to a named other power — "
                               f"they take it, you do not, and you may help "
                               f"them in."),
                      "false": f"Your orders do not hand {nm} to anybody else."})

    def run(build) -> set[str]:
        if not provs:
            return set()
        answers = caller(state, {p: build(p) for p in provs}).answers
        return {p for p in provs
                if float(getattr(answers[p], "noul", 0.0) or 0.0) >= threshold}

    keep_out = run(_bar)
    gifts = run(_gift) - keep_out
    return keep_out, gifts
