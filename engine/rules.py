"""The rules of Diplomacy, written out for a model that has to judge a position.

`engine.context.RULES_CRIB` is three reminders for an agent that already knows
the game. This is the whole ruleset, for Jev, which is handed a board cold and
asked to pick an order. Without it, "take supply centres" is an instruction with
no stated reason behind it.

Checked against the Avalon Hill / Hasbro rulebook (5th edition, 2008 text, 2014
printing), including its 22-point order-resolution checklist. Paraphrased
throughout rather than quoted — the rulebook text is copyrighted, the rules
themselves are not. Where this and the `diplomacy` package's adjudicator
disagree, the adjudicator is what actually decides the game.
"""
from __future__ import annotations

OBJECTIVE = """\
Diplomacy is a seven-player game of negotiation and simultaneous movement on a
map of Europe before the First World War. The Great Powers are Austria, England,
France, Germany, Italy, Russia and Turkey.

The board holds 34 supply centres. The moment one power controls 18 of them, it
has won outright; that is the only solo victory. Players may also agree to end
the game early, in which case everyone still on the board shares a draw.

Supply centres are also how you grow. Your unit count is set by the number of
centres you held at the end of the last Fall turn, so every centre gained is
another unit and every centre lost costs you one. A power reduced to no centres
is out of the game. This is why a unit standing idle in a quiet province is
usually wasting the turn — and why the opening year matters so much: the twelve
unowned neutral centres go to whoever reaches them first.\
"""

UNITS_AND_MAP = """\
Each power has armies and fleets. **Every unit is exactly as strong as every
other** — armies and fleets alike. Units win by outnumbering, never by quality.

**Only one unit may occupy a province at a time.** There are no exceptions.

Provinces are inland, water, or coastal. Armies move on inland and coastal
provinces, never on water. Fleets move on water and coastal provinces, never
inland. Either kind of unit may occupy a coastal province.

Fleet movement along the coast is narrower than it looks: a fleet moving between
two coastal provinces needs them to be adjacent *along the coastline*, not
merely to share a land border. A fleet in Rome can reach Tuscany or Naples, but
not Venice or Apulia.

Spain, Bulgaria and St Petersburg each have two distinct coasts. A fleet there
occupies the whole province but sits on one named coast and can only move on to
provinces adjacent to that coast. An order into such a province must name the
coast when both are reachable. Kiel and Constantinople, despite their waterways,
count as having a single coast, and armies cross them freely.

Switzerland is impassable and can never be entered or crossed.\
"""

SEASONS = """\
Each year is a Spring turn and a Fall turn. Every turn has negotiation, then
simultaneous secret order writing, then resolution, then retreats. After the
Fall retreats, units are built and disbanded.

**Supply-centre ownership only changes at the end of a Fall turn**, once its
retreats are done. You keep a centre as long as, at that moment, it is either
empty or holds one of your own units. Marching out of a centre in Spring and
being elsewhere in Fall costs you nothing. Taking a centre in Spring and leaving
before Fall ends gains you nothing.\
"""

ORDERS = """\
Every unit gets exactly one order per movement turn. A unit given no order, or
an illegal one, holds.

- **Hold.** Stay put.
- **Move.** Attempt to enter an adjacent province. Moving into an occupied
  province is an attack.
- **Support.** Give up your own move to add strength to another unit — either to
  a unit's move into a province, or to a unit staying where it is. You may only
  support action into or within a province **you could legally move to
  yourself**. An army cannot support anything into a sea; a fleet in Rome cannot
  support anything into Venice. (A fleet able to reach a two-coast province may
  support into it regardless of which coast.) You do not need to be adjacent to
  the unit you support, only to the province you are supporting into.
- **Convoy.** A fleet in a *water* province carries an army between two coastal
  provinces adjacent to it. Only fleets convoy, only armies are convoyed, and a
  fleet sitting in a coastal province cannot convoy at all.

**Support may be given to any power's unit, including a rival's, and it cannot
be refused.**\
"""

SUPPORT_AND_STRENGTH = """\
A unit's strength is 1, plus 1 for every valid support it receives.

**Moving into an empty province.** You get in unless another unit is also trying
to enter with equal or greater strength. If nobody is strictly strongest, all of
them bounce and stay where they began. This is a standoff, and it happens just
as readily between two units of the same power.

**Moving into an occupied province.** You must be strictly stronger than the
defender, counting any support it receives to hold. Equal strength fails and
you stay put.

**Standoffs do not dislodge.** A unit already sitting in the province where a
standoff happens is untouched by it.

**One stationary unit can jam a whole chain.** If a unit holds or is prevented
from moving, everything ordered into its province bounces, and everything
ordered into *those* provinces bounces in turn.

**Units cannot swap places** by moving into each other; both bounce. Three or
more units *can* rotate around a loop, as long as no two directly trade places.
The one exception to the swap rule is a convoy: two units may exchange places if
either of them is being convoyed.

**Support must match the order actually given.** Supporting a unit into a
province it was not ordered to enter does nothing — and it does not quietly
become a support to hold. Likewise, supporting a unit "in place" fails if that
unit turned out to be moving.

**Cutting support.** A supporting unit that is attacked from any province stops
supporting, whether or not the attack succeeds. There are two exceptions: an
attack coming *from the province the support is being given into* does not cut
it, and an attack by a power on **its own** unit never cuts that unit's support.
A supporting unit that is dislodged also stops supporting.

**Dislodged units still act elsewhere.** A unit that gets dislodged can still
cause a standoff in a different province, and can still cut support in a
different province. What it cannot do is affect the province its attacker came
from — a dislodged unit has no effect there, however much support it had. So if
two units are ordered into the same province and one of them is dislodged from
that direction, the other one gets in unopposed.

**You cannot dislodge your own unit.** Not with your own support, and not with a
foreign power's support either — the attack simply fails. But you *may*
deliberately bounce two of your own equally-supported units off a province to
keep anyone else out of it, which is a standard way to hold three provinces with
two units.\
"""

CONVOYS = """\
To convoy, the army is ordered to move to the destination and **every** fleet
along the water route is ordered to convoy that specific army to that specific
destination, in the same turn. A mismatch anywhere, or a missing link, and the
army does not move. A fleet may convoy only one army per turn. Support cannot be
convoyed.

If any fleet in the chain is dislodged, the convoy fails and the army stays
home. An attack that fails to dislodge a convoying fleet does not disturb it. If
orders leave more than one possible water route, the army still arrives as long
as at least one route survives.

If a convoyed army is stood off at its destination, it stays in the province it
started from.

When an army could reach its destination either overland or by convoy, the
convoy is used if any convoying fleet belongs to the army's own power; otherwise
the land route is used unless the army's order explicitly says to go by convoy.\
"""

RETREATS = """\
A dislodged unit retreats to an adjacent province it could normally have moved
to. It may **not** retreat into an occupied province, into the province its
attacker came from, or into a province left empty by a standoff that same turn.

Retreats cannot be supported or convoyed. If no legal destination exists, or if
two dislodged units both choose the same province, the units are disbanded and
removed. A unit may also choose to disband instead of retreating.\
"""

ADJUSTMENTS = """\
After each Fall turn, compare your supply-centre count with your unit count.

**Fewer centres than units:** disband the difference; you choose which units.

**More centres than units:** you may build, but **only in your own original home
supply centres**, and only those you still control and that are currently empty.
France builds only in Paris, Brest and Marseilles, ever. If your home centres are
all occupied you cannot build that turn, even with centres to spare, so leaving
one empty is worth planning for. A power that has lost all its home centres keeps
fighting with the units it has but cannot build until it retakes one. Building is
optional — you may decline.

Inland centres can only take an army. A coastal centre must specify army or
fleet, and St Petersburg must also specify which coast.\
"""

CIVIL_DISORDER = """\
A power that submits no orders holds every unit in place, with no unit
supporting any other. Dislodged units are disbanded outright and no new units
are built.\
"""

FULL_RULES = "\n\n".join([
    "# The rules of Diplomacy",
    "## The object of the game", OBJECTIVE,
    "## Units and the map", UNITS_AND_MAP,
    "## The year, and when centres change hands", SEASONS,
    "## The four orders", ORDERS,
    "## Strength, standoffs, support and dislodgement", SUPPORT_AND_STRENGTH,
    "## Convoys", CONVOYS,
    "## Retreats", RETREATS,
    "## Builds and disbands", ADJUSTMENTS,
    "## Civil disorder", CIVIL_DISORDER,
])
