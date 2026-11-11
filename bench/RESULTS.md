# Gunboat bench results

`before` = the board on main; `after` = with the season line and "Who can move into each centre". Mixed runs: 3 model seats, 2 random (`fake`), 2 `hold`, rotating powers.

Written by `bench/gunboat.py` (see its docstring for what each column counts). Rates are per movement phase, or per Fall phase for missed. missed and selfbounce are ramp-up signals only, to retire once seats are competent; gain is mean centres gained per seat.





## before — 2026-11-11, claude:haiku, 3 games to 1902

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | gain |
|---|---|---|---|---|---|---|---|---|
| fake | 6 | 0.00 | 0.00 | 0.00 | 0.25 | 0.38 | 1.38 | -0.17 |
| haiku | 9 | 0.03 | 0.03 | 0.00 | 0.22 | 0.00 | 0.00 | +2.56 |
| hold | 6 | 0.00 | 0.00 | 1.00 | 0.33 | 0.00 | 0.00 | +0.00 |

## after — 2026-11-11, claude:haiku, 3 games to 1902

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | gain |
|---|---|---|---|---|---|---|---|---|
| fake | 6 | 0.00 | 0.00 | 0.00 | 0.50 | 0.33 | 1.67 | +0.00 |
| haiku | 9 | 0.00 | 0.00 | 0.00 | 0.11 | 0.00 | 0.00 | +2.44 |
| hold | 6 | 0.00 | 0.00 | 1.00 | 0.33 | 0.00 | 0.00 | +0.00 |

## before-7 — 2026-11-11, claude:haiku, 2 games to 1904

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | gain |
|---|---|---|---|---|---|---|---|---|
| haiku | 14 | 0.04 | 0.04 | 0.00 | 0.02 | 0.00 | 0.00 | +1.71 |

## after-7 — 2026-11-11, claude:haiku, 2 games to 1904

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | gain |
|---|---|---|---|---|---|---|---|---|
| haiku | 14 | 0.01 | 0.01 | 0.00 | 0.05 | 0.00 | 0.00 | +1.57 |

## haiku-vs-random — 2026-11-11, claude:haiku, 3 games to 1906

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 18 | 0.00 | 0.00 | 0.00 | 0.31 | 0.20 | 1.56 | 0.00 | +0.56 |
| haiku | 3 | 0.00 | 0.00 | 0.00 | 0.11 | 0.00 | 0.00 | 0.00 | +4.33 |
