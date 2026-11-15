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

## flint-smoke — 2026-11-14, local:flint, 1 games to 1901

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 6 | 0.00 | 0.00 | 0.00 | 0.33 | 0.33 | 1.42 | 0.00 | +0.17 |
| flint@Cutie | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +2.00 |

## flint-2seats-cap1 — 2026-11-14, local:flint, 1 games to 1901

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 5 | 0.00 | 0.00 | 0.00 | 1.20 | 0.20 | 1.10 | 0.00 | +0.00 |
| flint@Cutie | 2 | 0.25 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +0.50 |

## flint-2seats-cap2 — 2026-11-14, local:flint, 1 games to 1901

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 5 | 0.00 | 0.00 | 0.00 | 0.40 | 0.10 | 1.20 | 0.00 | +0.20 |
| flint@Cutie | 2 | 0.25 | 0.25 | 0.00 | 1.00 | 0.00 | 0.50 | 0.00 | +0.50 |

## flint-vs-random-hold — 2026-11-14, local:flint, 3 games to 1902

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 9 | 0.00 | 0.00 | 0.00 | 0.83 | 0.08 | 1.47 | 0.00 | +0.33 |
| flint@Cutie | 3 | 0.00 | 0.00 | 0.00 | 0.33 | 0.08 | 0.50 | 0.00 | +0.67 |
| hold | 9 | 0.00 | 0.00 | 1.00 | 0.44 | 0.00 | 0.00 | 0.00 | +0.00 |

### Local seats on Cutie (flint via LM Studio): phase time, 2026-11-15

flint has one fixed reasoning level and reasons to the 8000-token cap on every call (~30k characters), so a call takes ~150 s. Wall time per phase is the slowest local seat:

| local seats | calls at once | S1901M | F1901M | W1901A |
|---|---|---|---|---|
| 1 | 1 | 154 s | 152 s | 246 s (finishing call) |
| 2 | 1 | 237 s (finishing call) | 296 s | 146 s |
| 2 | 2 | 310 s (finishing call) | 229 s | 79 s |

One GPU: two calls at once each run slower, so a phase takes about as long either way. The cap stays at 1 (`concurrency` in the host's local config). With 1 h turns, even seven local seats (~18 min a phase) fit.

## haiku-1seat-vs-random-hold — 2026-11-14, claude:haiku, 3 games to 1902

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 9 | 0.00 | 0.00 | 0.00 | 0.50 | 0.17 | 1.42 | 0.00 | +0.44 |
| haiku | 3 | 0.00 | 0.00 | 0.00 | 0.17 | 0.00 | 0.00 | 0.00 | +3.00 |
| hold | 9 | 0.00 | 0.00 | 1.00 | 0.22 | 0.00 | 0.00 | 0.00 | -0.11 |

## sonnet-1seat-vs-random-hold — 2026-11-14, claude:sonnet, 3 games to 1902

| seats | n | finishing/phase | refused/phase | held/phase | missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |
|---|---|---|---|---|---|---|---|---|---|
| fake | 9 | 0.00 | 0.00 | 0.00 | 0.56 | 0.31 | 1.31 | 0.00 | +0.11 |
| hold | 9 | 0.00 | 0.00 | 1.00 | 0.22 | 0.00 | 0.00 | 0.00 | -0.11 |
| sonnet | 3 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +4.00 |

### One model seat vs 3 random + 3 hold, 3 games to 1902 (same powers each game: Austria, England, France)

| seat | final centres (A / E / F) | gain | refused/phase | void supports/phase | missed/fall |
|---|---|---|---|---|---|
| flint (local, Cutie) | 4 / 3 / 4 | +0.67 | 0.00 | 0.50 | 0.33 |
| Haiku | 6 / 6 / 6 | +3.00 | 0.00 | 0.00 | 0.17 |
| Sonnet | 7 / 7 / 7 | +4.00 | 0.00 | 0.00 | 0.00 |

flint's orders are always legal (it copies from the lists) but half its phases include a support that doesn't match the supported unit's move, and it barely outgrows random (+0.33). A weak opponent for now; worth re-running when another local model is loaded.
