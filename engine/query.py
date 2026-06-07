"""Board queries — the backbone of the check-board-state skill.

Answers the "silly questions" an agent needs: what's where, who owns which
supply centers, what's adjacent to what, and how many builds/disbands each
power owes. Everything is derived from the live engine so it can never drift
from the authoritative state.
"""
from __future__ import annotations

from diplomacy import Game


def board_summary(game: Game) -> dict:
    """High-level snapshot of the whole board."""
    powers = {}
    for name, power in game.powers.items():
        centers = list(power.centers)
        units = list(power.units)
        powers[name] = {
            "units": units,
            "centers": centers,
            "unit_count": len(units),
            "center_count": len(centers),
            "adjustment": len(centers) - len(units),  # +build / -disband
        }
    return {
        "phase": game.get_current_phase(),
        "phase_type": game.phase_type,
        "done": game.is_game_done,
        "powers": powers,
    }


def units_at(game: Game, province: str) -> list[str]:
    """Owner-tagged units occupying a province (ignores coast suffix)."""
    prov = province.upper().split("/")[0]
    found = []
    for name, power in game.powers.items():
        for unit in power.units:
            if unit.split()[1].split("/")[0] == prov:
                found.append(f"{name}: {unit}")
    return found


def owner_of_center(game: Game, province: str) -> str | None:
    prov = province.upper().split("/")[0]
    for name, power in game.powers.items():
        if prov in power.centers:
            return name
    return None


def adjacencies(game: Game, province: str) -> list[str]:
    """Provinces adjacent to `province` (raw map adjacency)."""
    prov = province.upper()
    abut = game.map.loc_abut.get(prov) or game.map.loc_abut.get(prov.lower())
    return sorted(a.upper() for a in (abut or []))


def province_info(game: Game, province: str) -> dict:
    prov = province.upper().split("/")[0]
    return {
        "province": prov,
        "type": game.map.area_type(prov),
        "is_supply_center": prov in game.map.scs,
        "owner": owner_of_center(game, prov),
        "occupied_by": units_at(game, prov),
        "adjacent": adjacencies(game, prov),
    }


def adjustment_summary(game: Game) -> dict[str, int]:
    """Per-power build (+) / disband (-) count: centers minus units."""
    return {
        name: len(power.centers) - len(power.units)
        for name, power in game.powers.items()
    }
