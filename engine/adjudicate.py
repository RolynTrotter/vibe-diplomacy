"""Pure adjudication: (game, orders) -> advanced game.

This module does no file I/O. It takes a live Game and a mapping of power ->
orders, applies them, and advances one phase. Missing or invalid orders fall
back to the engine's defaults (holds in movement, disband on failed retreat,
waive on unused builds), which matches Diplomacy's civil-disorder handling.
"""
from __future__ import annotations

from diplomacy import Game


def apply_orders(game: Game, orders_by_power: dict[str, list[str]]) -> None:
    for power, orders in orders_by_power.items():
        game.set_orders(power.upper(), list(orders), expand=True, replace=True)


def adjudicate(game: Game, orders_by_power: dict[str, list[str]]) -> dict:
    """Apply orders and process one phase.

    Returns a summary of the phase that was just resolved:
        {phase, orders: {power: [...accepted...]}, results: {unit: [...]}}
    """
    phase = game.get_current_phase()
    apply_orders(game, orders_by_power)
    accepted = {power: game.get_orders(power) for power in game.powers}
    game.process()

    results = {}
    try:
        results = {unit: res for unit, res in game.result_history.last_value().items()}
        results = {unit: [str(r) for r in res] for unit, res in results.items()}
    except (AttributeError, IndexError, KeyError):
        pass

    return {"phase": phase, "orders": accepted, "results": results}
