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


## fa-haiku-vs-random — 2026-11-11, claude:haiku, 4 games to 1906, France vs Austria

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 4 | 0.00 | 0.00 | 0.00 | 2.35 | 0.15 | 1.50 | 0.00 | +3.25 |
| haiku | 4 | 0.02 | 0.02 | 0.00 | 0.61 | 0.00 | 0.00 | 0.00 | +11.75 |

## fa-haiku-vs-haiku — 2026-11-11, claude:haiku, 2 games to 1906, France vs Austria

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| haiku | 4 | 0.00 | 0.00 | 0.00 | 0.58 | 0.00 | 0.00 | 0.00 | +12.25 |

## fa-france-base — 2026-11-11, claude:haiku, 3 games to 1906, France vs Austria

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 3 | 0.00 | 0.00 | 0.00 | 2.33 | 0.31 | 1.72 | 0.00 | +4.00 |
| haiku | 3 | 0.00 | 0.00 | 0.00 | 0.22 | 0.00 | 0.00 | 0.00 | +9.67 |
## fa-france-e1 — 2026-11-11, claude:haiku, 3 games to 1906, France vs Austria

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 3 | 0.00 | 0.00 | 0.00 | 3.29 | 0.18 | 1.91 | 0.00 | +2.67 |
| haiku | 3 | 0.00 | 0.00 | 0.00 | 0.06 | 0.00 | 0.00 | 0.00 | +12.33 |
## fa-france-e2 — 2026-11-11, claude:haiku, 3 games to 1906, France vs Austria

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 3 | 0.00 | 0.00 | 0.00 | 2.06 | 0.15 | 2.15 | 0.00 | +3.33 |
| haiku | 3 | 0.00 | 0.00 | 0.00 | 0.35 | 0.00 | 0.00 | 0.00 | +15.33 |

### fa-france arms compared (Haiku always France, vs random Austria, 3 games each)

| arm | gain by 1902 | by 1904 | by 1906 | missed/Fall | finals France-Austria (France idle phases) |
|---|---|---|---|---|---|
| base | +4.67 | +7.67 | +9.67 | 0.22 | 9-7 (6/12 idle), 13-5 (1/12 idle), 16-9 (1/12 idle) |
| e1: board lists only centres you can take | +5.00 | +10.00 | +12.33 | 0.06 | 10-7 (4/12 idle), 18-6 (0/12 idle), 18-4 (0/10 idle) |
| e2: notebook asks which centres to take next | +6.00 | +11.33 | +15.33 | 0.35 | 19-8 (1/12 idle), 17-6 (0/12 idle), 19-5 (0/10 idle) |

"Idle" = a movement phase where France only held or supported. Base game 1's notebook: "Holding everywhere again ... Consider KIE only once MUN has a second defender."
