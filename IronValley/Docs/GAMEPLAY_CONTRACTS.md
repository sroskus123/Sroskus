# IRON VALLEY — rozhraní herních systémů (web)

Závazný kontrakt mezi herní integrací (`src/game`, `src/weapons`, `src/player`) a AI (`src/ai`). Mění se jen dohodou
a zápisem sem. Cílem je, aby boti a hráč používali **stejná pravidla pohybu, munice, zásahů a viditelnosti**
(zadání §7) a lišili se jen zdrojem příkazů.

## Vlastnictví souborů

| Oblast | Vlastník | Poznámka |
| --- | --- | --- |
| `src/game/**`, `src/weapons/**`, `src/player/**`, `src/main.js`, `src/styles.css`, `src/data/*.json` (kromě AI) | herní integrace | včetně `game.js`, HUD, menu, spawnů |
| `src/ai/**`, `Shared/config/ai.json`, `tools/bake_navmesh.mjs`, `src/data/ai_arena.json` | AI | navmesh se peče v buildu (rozhodnutí D4) |
| `src/core/**`, `Core/**`, `Shared/testvectors/**` | jádro pravidel | měnit jen s úpravou obou jader a vektorů |
| `src/engine/**`, `src/physics/**`, `src/level/**` | sdílené | měnit opatrně, zachovat testy |

## Combatant (`src/game/combatant.js`)

Jeden bojovník = hráč nebo bot. Vlastní:

- `id` (řetězec), `team` (0, 1, 2), `isPlayer` (bool), `name`
- `controller` — sdílený `CharacterController` (kapsle r 0,35 m, výška 1,80 / 1,20 m)
- `yaw`, `pitch` (radiány, yaw 0 = pohled −Z v three.js), `getEye(out)` — poloha oka v simulaci
- `weapons` — `[primary, secondary]`, každá = autoritativní `WeaponState` z `src/core/weapon.js` + hitscan se stejným
  ověřením ústí jako u hráče (D8); `activeWeapon`
- `alive`, `health` — autoritativně z `Match` (`src/core/match.js`); zbraně mají zámky `disable/enable(reason)`
- `hitShapes()` — kapsle/koule pro zásahové zóny `head`, `torso`, `arm`, `leg` (násobky poškození v datech)
- `applyCommand(cmd, dt)` — jediný vstup chování; **hráč i bot používají stejný formát**

```js
cmd = {
  moveX, moveZ,        // −1..1, lokální vůči yaw (moveZ + = dopředu); úhlopříčka se normalizuje v kontroleru
  yaw, pitch,          // cílový pohled; u botů omezuje kontroler rychlost otáčení (turnRateDegPerSec v ai.json)
  sprint, walk, crouch, jump,
  ads, fire,           // fire = spoušť držena; kadenci a munici řeší WeaponState
  reload, switchTo,    // switchTo: null | 0 | 1
  interact,
}
```

`CombatantManager` (`src/game/combatants.js`) drží seznam, vytváří bojovníky přes `Match.addParticipant`,
provádí spawn/respawn podle `Match` a poskytuje dotazy `all()`, `alive()`, `byTeam(t)`, `get(id)`.

## Události (event bus `src/engine/events.js`)

| Název | Data |
| --- | --- |
| `weapon:fired` | `{ shooterId, team, weaponId, muzzle, dir, loudness }` |
| `weapon:hit` | `{ shooterId, victimId \| null, point, normal, surface, part, blocked }` |
| `combatant:damaged` | `{ victimId, attackerId, amount, part, fromDir }` |
| `combatant:died` | `{ victimId, attackerId, position }` |
| `combatant:spawned` | `{ id, team, position, yaw }` |
| `footstep` | `{ id, team, position, surface, loudness }` |
| `weapon:reload_started` / `weapon:reload_finished` / `weapon:reload_interrupted` | `{ id, weaponId, kind }` |
| `round:started` / `round:ended` / `round:reset` | `{ zoneId?, winner?, scores? }` |
| `zone:control_changed` | `{ zoneId, controller \| null }` |

AI nesmí číst skutečnou polohu nepřítele mimo vnímání; smí reagovat jen na tyto události (se vzdáleností a útlumem
podle `ai.json`) a na vlastní paprsky viditelnosti.

## Dotazy na svět (`src/game/worldQuery.js`)

- `raycastStatic(origin, dir, maxDist)` — statická geometrie (BVH)
- `lineOfSight(fromPoint, toPoint, { ignoreId })` — statická geometrie + kapsle bojovníků; `true` jen při volném výhledu
- `surfaceAt(point)` — typ povrchu pro kroky a zásahy

## Navigace a kryty (`src/ai/nav`, `src/ai/cover`)

- Navmesh se peče nástrojem `tools/bake_navmesh.mjs` (recast-navigation jen v Node) z kolizní geometrie úrovně do
  `public/assets/nav/<level>.json`; za běhu `three-pathfinding` (čistý JS).
- `NavService`: `findPath(from, to)`, `closestPoint(p)`, `randomPointNear(p, r)`, `isReachable(from, to)`.
- `CoverService`: body krytu `{ id, pos, normal, height: 'low' | 'high' }` z analýzy geometrie při buildu;
  `reserve(botId, coverId)` je výlučná, `release(botId)`; žádné dva boty na stejném bodě.

## AI (`src/ai/index.js`)

```js
export function createAISystem({ combatants, world, nav, cover, events, match, config }) → {
  addBot(combatant), removeBot(id),
  update(dt),            // pevný tik; vnímání ~10 Hz rozložené mezi boty, rozhodování ~4–5 Hz, řízení každý tik
  getDebug(),            // stav vnímání, paměti, úkolu a cesty pro testy (window.__IV)
  reset(),               // nové kolo: vymaže paměť, rezervace krytů, cesty
}
```

Herní integrace nejdřív vytvoří **stub** `src/ai/index.js` se stejnou signaturou (nic nedělá) a zapojí ho do smyčky.
AI stub nahradí skutečnou implementací se stejným rozhraním.

Stav (AI, 2026-09-26): stub nahrazen, rozhraní beze změny. Doplňky, které rozhraní nemění: při `nav`/`cover` = `null`
si AI vezme zapečený navmesh a kryty podle `config.levelId` (`src/ai/nav/navRegistry.generated.js`, generuje
`tools/bake_navmesh.mjs`, peče se každá úroveň s blokem `match`); `config.tuning` přepisuje `ai.json` (testy);
`addBot` zapíše `ai.json turnRateDegPerSec` do `combatant.turnRateDegPerSec`; `dispose()` odhlásí události;
ladicí API `window.__IV.ai`; v datech úrovně příznaky `"nav": false` (solid mimo navmesh) a `"spawnShelter": true`
(kryty se v něm nevybírají) a bloky `nav`, `aiTest`. AI z `combatant:damaged` čte jen `fromDir`, ne `attackerPosition`.
Podrobnosti a naměřené hodnoty: `Docs/AI.md`.

## Konfigurace

- `Shared/config/rules.json` — pravidla zápasu a zbraní (jádro)
- `Shared/config/ai.json` — reakční doba, chyba míření, dávky, zorné pole, dosah sluchu, paměť, intervaly, rychlost otáčení
- `src/data/*.json` — pohyb, vstup, nastavení, prostředí

## Doplnění z herní integrace (2026-09-26, stav implementace)

Upřesnění, jak je kontrakt implementovaný v `src/game/**`. Nic z výše uvedeného se nemění, jen se doplňuje.

### Krok simulace a řízení bojovníků

- `MatchSession.tick(dt)` (`src/game/session.js`, bez DOM, běží i v Node): přítomnost v oblasti → `Match.update`
  (respawny v přesných okamžicích, bodování, čas kola) → `player.applyCommand` → `ai.update(dt)` → nečinný příkaz
  pro každého bojovníka, kterého v tomto tiku nikdo neřídil (`CombatantManager.stepUndriven`) → terče.
- **Každý bojovník dostane `applyCommand` právě jednou za tik.** AI volá `applyCommand` jen pro živé boty, které řídí;
  mrtvé a neřízené krokuje hra (zbraně se aktualizují každý tik se skutečným stavem spouště, jak vyžaduje jádro).
  Ověřuje unit test „AI contract“ se skutečnou AI.
- `applyCommand` mrtvého bojovníka ignoruje pohyb, pohled i přebití; spoušť se jádru předává dál (zámek `life`
  střelbu blokuje a spoušť držená přes smrt po respawnu nevystřelí).
- `combatant.turnRateDegPerSec` (výchozí `src/data/combat.json` → `bots.turnRateDegPerSec`) omezuje otáčení bota;
  AI ho smí nastavit v `addBot`. Hráč se otáčí bez omezení.
- Poškození: zásah bojovníka → `Match.applyDamage(oběť, round(damage × násobek zóny), střelec)`; násobky
  `src/data/combat.json` → `hitZones`, poškození zbraně z `rules.json`. Friendly fire řeší jádro (`rules.json`).

### Parametry `createAISystem` od hry

`nav` a `cover` předává hra jako `null` (AI si je vytvoří z napečeného navmeshe `config.levelId`), `world` =
`WorldQuery`, `combatants` = `CombatantManager`, `match` = `Match`. `config = { levelId, level, rules, zones,
session }` (`session.activeZone()`, `session.mode` = `'match' | 'practice'`, `session.seed`). Při zahození
relace hra volá `ai.dispose()`, pokud existuje (odhlášení z event busu).

### Další události

| Název | Data |
| --- | --- |
| `combatant:friendly_fire_blocked` | `{ victimId, attackerId, amount }` |
| `weapon:switched` | `{ id, weaponId, slot }` |
| `weapon:dry_fire` | `{ id, weaponId }` |
| `weapon:action` | `{ id, weaponId, type: 'mag_insert' \| 'bolt_release' \| 'chamber_commit' }` |
| `round:pre` | `{ zoneId, preRoundS }` |

`combatant:damaged` nese navíc `attackerPosition` (jen pro HUD hráče; AI ho podle kontraktu nečte) a `health`;
`combatant:died` nese `weaponId`, `part`, `team`. Háček pro fyzikální ragdoll: `combatant:died` +
`Combatant.deathPose` (zatím stabilní procedurální pád v `characterView.js`).

### Úroveň (`src/data/<id>.json`)

Stávající schéma (`solids`, `signs`, `banners`, `dummies`, `markers`) + volitelný blok `match`:

```json
"match": {
  "practiceSpawn": "spawn",
  "teamSpawns": [ [ { "pos": [x, y, z], "yaw": deg }, ... ], [ ... ], [ ... ] ],
  "zones": [ { "id": "zone_x", "name": "Název", "center": [x, y, z], "radius": 5, "height": 4 }, ... ]
}
```

- `teamSpawns[t]` = kandidátní body týmu `t` (pořadí týmů = `rules.json teams.list`), body ≥ 2,5 m od sebe, kryté
  před výhledem z mapy (predikát spawnu odmítá body viditelné živým nepřítelem).
- `zones` = tři umístění oblasti; hra je předá jádru jako `zone.locations` (jádro vybírá aktivní oblast semenem).
- Pevné těleso smí mít `"bvhGroup": "<název>"` — dostane vlastní kolizní BVH. Přidaná geometrie (např. kryty spawnů)
  tak nemění pořadí kontaktů kontroleru v základní úrovni.
- Načtení: `loadLevelData(id)` (`src/game/levels.js`), v prohlížeči `window.__IV.loadLevel(id)`; seznam pro nabídku
  `src/data/levels.json`.
