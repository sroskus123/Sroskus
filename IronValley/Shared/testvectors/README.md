# Sdílené testovací vektory

Stejné soubory přehrává JS (`Web/tests/unit/support/vector_runner.mjs`, test `core_vectors.test.mjs`) i C++
(`Core/tests/vector_runner.cpp`, `ctest`). Pravidla, která vektory ověřují: `Docs/RULES.md`.

## Soubor

```json
{ "schema": "ironvalley.testvectors", "version": 1, "suite": "weapon", "description": "...", "cases": [ ... ] }
```

Případ: `id`, `kind` (`weapon` | `zone` | `round` | `respawn` | `match` | `rules` | `rng`), volitelně `rules`
(JSON Merge Patch nad `Shared/config/rules.json`), `setup`, `tickModes` a `steps`.

## Kroky

Každý krok má `op` a volitelně `expect`. Po kroku vznikne `{result, events, snapshot}`.

| Druh | `setup` | Operace |
| --- | --- | --- |
| `weapon` | `weapon`, volitelně `magazine`, `chamber`, `reserve`, `fireMode` | `tick {dtUs, trigger, repeat}`, `run {durationUs, trigger, ticks}`, `reload`, `interrupt {reason}`, `disable {reason}`, `enable {reason}`, `setFireMode {mode}`, `resupply {rounds}`, `resetToLoadout` |
| `zone` | — | `tick {dtUs, participants, repeat}`, `run {durationUs, ticks, participants}`, `reset` |
| `round` | `seed` | jako `zone` + `start` |
| `respawn` | `seed`, `spawnAreas`, `participants` | `add {id, team, loadout}`, `kill {id}`, `damage {id, amount, attacker}`, `setLoadout {id, loadout}`, `tick`/`run {…, bodies, blocked}`, `resetRound`, `weapon {id, weapon, do: krok zbraně}`, `weaponEvents {id, weapon}`, `disableInput {id, reason}`, `enableInput {id, reason}` |
| `match` | jako `respawn` | jako `respawn` (místo `resetRound` je `reset`) + `start`, `tick`/`run {…, inZone, inactive}` |
| `rules` | — | `compile {overrides}` → `valid` / `invalid`, snímek = zkompilovaná pravidla |
| `rng` | `seed` | `next {count}`, `pick {n, count}`, `shuffle {n}` |
| všechny | | `loop {count, steps}` — opakuje vnořené kroky (uvnitř bez kontrol), výsledek `ok` |

- Účastník oblasti: objekt `{id, team, alive, active, inZone}` nebo pole `[id, team, alive, active, inZone]`.
- `trigger` platí jen pro daný krok (výchozí `false`). Vstupy světa `participants`, `bodies`, `blocked`, `inZone`,
  `inactive` jsou „lepivé“: platí, dokud je další krok nepřepíše.
- `blocked` = `{ "tým": [indexy kandidátů] }` (simuluje kolizi/viditelnost z predikátu enginu), `bodies` =
  `[{team, alive, pos: [x,y,z]}]` pro vzdálenostní část predikátu.
- `weapon` nejdřív zahodí dosud neodebrané události zbraně a vrátí jen události svého kroku; `weaponEvents` vrátí
  události, které zbraň nashromáždila od posledního kroku `weapon` (např. `reload_interrupted` při smrti nebo resetu kola).
- Snímek respawnu obsahuje `reservedUs[tým][index]` (zbývající rezervace bodů), účastník `inputLocks` a zbraň `disabledBy`
  (aktivní zámky v pevném pořadí `life`, `sprint`, `switch`, `menu`, `results`, `other`).
- `ticks`: `{hz: N}` (hranice `round(k·10^6/N)`), `{dtUs: N}`, `{irregular: {seed, minUs, maxUs}}` (délky z mulberry32;
  jeden proud na případ a režim) nebo `"case"` = aktuální režim z `tickModes` případu. S `tickModes` se celý případ
  spustí pro každý režim a očekávání musí platit ve všech (nezávislost na délce tiku).

## Kontrola tvaru

Oba spouštěče tvar vektoru kontrolují a chybu hlásí jako chybu případu (nikdy tichý PASS): povolené jsou jen klíče
z tabulky výše (+ `op`, `expect`, u případu `id`, `kind`, `description`, `rules`, `setup`, `tickModes`, `steps`),
`expect` nesmí být uvnitř `loop` ani `do` (tam se nekontroluje), `trigger`, `alive`, `active`, `inZone` musí být
`true`/`false`, účastník oblasti pole o 5 prvcích nebo objekt s pěti klíči, tělo `{team, alive, pos}` a režim tiku
objekt s právě jedním z klíčů `hz`, `dtUs`, `irregular`. Hlavička souboru smí mít jen `schema`, `version`, `suite`,
`description`, `cases` a u generovaných souborů `generated`, `generator`, `masterSeed`. Zkouška: `malformed/cases.json`
(dvojice chybný případ + tentýž bez chyby; JS `core_runner.test.mjs`, C++ `ctest runner.malformed`).

## Očekávání (`expect`)

- `result` — přesná shoda výsledku operace; `events` — přesný seznam událostí kroku; `eventCounts` — počty podle typu;
- `snapshot` — přesná shoda celého stavu; `snapshotDigest` — FNV-1a 64 (16 hex) kanonického JSON stavu
  (seřazené klíče, bez mezer, UTF-8);
- ostatní klíče = podmnožina stavu (objekty rekurzivně, pole musí mít stejnou délku).

Oba spouštěče navíc po každém tiku kontrolují invariant munice všech zbraní (u respawnu a zápasu všech zbraní, které
účastník kdy dostal, i mimo aktuální výbavu).

## Soubory

| Soubor | Obsah | Původ očekávání |
| --- | --- | --- |
| `weapon.json`, `zone.json`, `round.json`, `respawn.json`, `match.json`, `rules.json` | ruční případy GUN-01, GUN-03, GAME-01, GAME-02 | ručně z pravidel; hodnoty závislé na semeni nezávisle ověřuje `tools/seed_reference.py` |
| `rng.json` | výstupy generátoru | referenční mulberry32 v Pythonu; ověřuje `tools/seed_reference.py` |
| `fuzz_*.json` | diferenciální fuzz (**generované, needitovat**) | JS jádro (`node Web/tests/unit/support/generate_fuzz_vectors.mjs`); C++ je musí reprodukovat |

## Nezávislá kontrola v Pythonu

`tools/seed_reference.py` (Python 3, jen standardní knihovna) nepoužívá JS ani C++ jádro. Podle `Docs/RULES.md` znovu
implementuje generátor mulberry32, výběr oblasti kola a životní cyklus respawnu a přehraje soubory vektorů:

- `rng.json`: všechny výstupy generátoru a konečný stav;
- vektory kola a zápasu (ruční i fuzz): `zoneIndex` a `zoneId`;
- vektory respawnu (ruční i fuzz): výsledky a události operací respawnu včetně indexů bodů spawnu, pole životního cyklu
  účastníků, zámky vstupu (`inputLocks`) a rezervace bodů (`reservedUs`); stav zbraní a `snapshotDigest` ověřuje až
  JS/C++ spouštěč.

```bash
python3 Shared/testvectors/tools/seed_reference.py        # 0 = vše sedí, 1 = neshoda (vypíše ji)
```

ctest ji spouští jako test `seed_reference`, pokud CMake najde Python 3.
