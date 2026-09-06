"""Board pictures — a labelled PNG of the current position, per phase.

Agents reason badly about a map they can only read as prose. The `diplomacy`
package can already draw the board, but its output is unusable as-is for two
reasons, both worked around here:

1. **The renderer hides province names by default.** `Game.render()` drops the
   map's `BriefLabelLayer` unless `incl_abbrev=True`, so the stock picture is
   coloured blobs with no way to name anything in an order.
2. **Those labels are styled by a CSS class that cairosvg mis-applies**, which
   paints the whole canvas black. So we re-emit the label layer with inline
   presentation attributes instead of `class="labeltext24"`.

On top of that we add a legend (nothing on the stock map says which colour is
which power) and render to PNG, cached per phase.

cairosvg is optional: it needs a system libcairo, so every entry point degrades
to "no picture" with a readable reason rather than breaking a turn.
"""
from __future__ import annotations

import re
from pathlib import Path

from diplomacy import Game

# Power fill colours, copied from the map's own stylesheet so the legend can
# never disagree with the picture it explains.
POWER_COLORS = {
    "AUSTRIA": "#c48f85", "ENGLAND": "darkviolet", "FRANCE": "royalblue",
    "GERMANY": "#a08a75", "ITALY": "forestgreen", "RUSSIA": "#757d91",
    "TURKEY": "#b9a61c",
}

BOARD_DIR = ".board"          # gitignored: derived, never committed
DEFAULT_WIDTH = 1600

_LABEL_LAYER_RE = re.compile(
    r'<g class="labeltext24" id="BriefLabelLayer">(.*?)</g>', re.S)


def available() -> tuple[bool, str]:
    """(can we render PNGs, why not) — cairosvg needs a system libcairo."""
    try:
        import cairosvg  # noqa: F401
    except Exception as exc:   # ImportError, or OSError when libcairo is absent
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _inline_labels(svg: str) -> str:
    """Restyle the province-abbreviation layer with presentation attributes.

    cairosvg renders the whole map black when the layer keeps its
    `labeltext24` class, so the class goes and the styling is inlined. Sizes
    match the map's two label tiers (the `labeltext18` members are the
    cramped provinces, drawn smaller).
    """
    def repl(match: re.Match) -> str:
        inner = match.group(1)
        inner = inner.replace('class="labeltext18"', 'font-size="20"')
        return ('<g id="ProvinceLabels" font-family="DejaVu Sans, sans-serif" '
                'font-size="26" font-weight="bold" fill="black" stroke="none" '
                f'text-anchor="middle">{inner}</g>')

    return _LABEL_LAYER_RE.sub(repl, svg, count=1)


def _legend(game: Game) -> str:
    """A colour key with each power's centre count — the stock map has none."""
    rows = []
    for i, (name, color) in enumerate(POWER_COLORS.items()):
        power = game.powers.get(name)
        count = len(power.centers) if power else 0
        y = 40 + i * 34
        rows.append(
            f'<rect x="20" y="{y - 20}" width="26" height="26" fill="{color}" '
            f'stroke="black" stroke-width="1"/>'
            f'<text x="56" y="{y}" font-family="DejaVu Sans, sans-serif" '
            f'font-size="24" fill="black">{name} — {count}</text>')
    return (f'<g id="Legend"><rect x="8" y="8" width="250" height="{len(rows) * 34 + 16}" '
            f'fill="white" fill-opacity="0.85" stroke="black" stroke-width="1"/>'
            + "".join(rows) + "</g>")


def board_svg(game: Game, *, orders: bool = True, legend: bool = True) -> str:
    """The current position as an SVG string: labelled, with a colour key."""
    svg = game.render(incl_orders=orders, incl_abbrev=True)
    svg = _inline_labels(svg)
    if legend:
        svg = svg.replace("</svg>", _legend(game) + "</svg>", 1)
    return svg


def board_png(game: Game, path: Path, *, width: int = DEFAULT_WIDTH,
              orders: bool = True) -> Path | None:
    """Write the position to `path` as a PNG. None if cairosvg is unusable."""
    ok, _ = available()
    if not ok:
        return None
    import cairosvg

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=board_svg(game, orders=orders).encode("utf-8"),
                     write_to=str(path), output_width=width)
    return path


def phase_image(root: Path, game: Game, *, width: int = DEFAULT_WIDTH) -> Path | None:
    """The cached picture for the game's current phase, rendering if needed.

    One shared image per phase: the board is public, so a per-power render
    would be seven identical files. Cached against `state/current.json` so a
    brief regenerated mid-phase (after negotiation, say) reuses the render but
    a new phase always redraws.
    """
    root = Path(root)
    path = root / BOARD_DIR / f"{game.get_current_phase()}.png"
    state_file = root / "state" / "current.json"
    if path.exists():
        fresh = (not state_file.exists()
                 or path.stat().st_mtime >= state_file.stat().st_mtime)
        if fresh:
            return path
    try:
        return board_png(game, path, width=width)
    except Exception:
        # A picture is an aid, never a blocker: a broken render must not cost
        # a power its turn.
        return None


def image_data_uri(path: Path) -> str:
    """`data:image/png;base64,...` — how vision models take an inline image."""
    import base64
    raw = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


__all__ = ["POWER_COLORS", "BOARD_DIR", "available", "board_svg", "board_png",
           "phase_image", "image_data_uri"]
