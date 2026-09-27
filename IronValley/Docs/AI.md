# IRON VALLEY — AI botů (prohlížečová verze)

Tento dokument popisuje umělou inteligenci botů ve webové verzi (three.js, čistý JavaScript bez WebAssembly),
testovací mapu **AI aréna**, pečení navmeshe, všechny laditelné hodnoty a **naměřené výsledky** testů AI-01 až AI-04
z `Docs/zadani/02_PRAVIDLA_KVALITY_A_TESTY.md`. Kód AI je v `Web/src/ai/`, laditelné hodnoty v `Shared/config/ai.json`.

> Vše níže platí pro webovou verzi. V Unreal Engine nic z toho spuštěno nebylo (UE v prostředí není).
> Výkon na skutečném hardwaru (GPU, 60 FPS) **NOT TESTED** — měřeno jen v Node a v headless Chromiu se SwiftShaderem
> s vypnutým vykreslováním, na sdíleném stroji pod zátěží.

## 1. Stav v kostce

| Oblast | Stav | Důkaz |
| --- | --- | --- |
| AI aréna (`src/data/ai_arena.json`) | hotovo | 71 × 71 m, střed + 2 další kandidáti oblasti, 3 kryté spawny, dvoupatrový dům se schody, dveřmi a okny, ulička 1,5 m, otevřený průchod 4 m, zátaras mimo navmesh |
| Navmesh při buildu (`tools/bake_navmesh.mjs`, recast-navigation jen v Node) | hotovo | `npm run build` nejdřív peče; `ai_nav.test.mjs` kontroluje aktuálnost (`--check`) |
| Body krytu z geometrie | hotovo | 527 bodů (low 103, high 424, okno 2, s pozicí vyklonění 180); test ověřuje výšku překážky paprsky |
| Vnímání (zrak, sluch, zásah) + paměť | hotovo | AI-01 a–d PASS (Node i prohlížeč) |
| Rozhodování (utility), kryty, dávky, přebíjení, pátrání | hotovo | AI-03, AI-04 PASS |
| Pohyb (navmesh, vyhýbání, zaseknutí bez teleportu) | hotovo | AI-02 PASS (17 botů, zablokovaná cesta) |
| Ladění `window.__IV.ai` + 3D překryv | hotovo | e2e snímky `tests/e2e/screens/ai_overlay_*.png` |
| Výkon na reálném GPU | NOT TESTED | jen software (SwiftShader), vykreslování vypnuté |

## 2. Architektura

```
src/ai/
  index.js        createAISystem(...) — kontraktní rozhraní (Docs/GAMEPLAY_CONTRACTS.md), události, tik, ladicí API
  bot.js          jeden bot: rozhodování (utility, ~4,5 Hz) + provedení každý tik → cmd pro Combatant.applyCommand
  perception.js   zrak (paprsky k bodům těla), sluch (výstřely, kroky), zásah (směr)
  memory.js       paměť nepřátel: poslední známá poloha / čas / rychlost, důvěra, zapomínání
  aim.js          míření: omezená rychlost otáčení, model chyby (Ornstein–Uhlenbeck), usazování při sledování
  steering.js     sledování cesty, vyhýbání, detekce zaseknutí a obnova (nikdy teleport)
  tactics.js      výběr krytu proti hrozbě, pozice v oblasti, rozestupy týmu (TeamBoard)
  config.js       načtení a kontrola Shared/config/ai.json (+ přepisy pro testy)
  debug.js        window.__IV.ai a 3D překryv (cesty, poslední známé polohy, kryty, zablokovaná místa)
  nav/navMesh.js  navmesh za běhu: mřížka trojúhelníků, nejbližší bod, metrické A*, string pulling (funnel)
  nav/navService.js      NavService: findPath / closestPoint / randomPointNear / isReachable + blokace oblastí
  nav/navRegistry.generated.js  (generuje bake) statické importy zapečených navmeshů do balíku
  cover/coverService.js  CoverService: body krytu, výlučná rezervace
tools/bake_navmesh.mjs   pečení navmeshe a bodů krytu (Node, WASM jen zde — rozhodnutí D4)
public/assets/nav/<level>.json   výstup pečení (formát zóny three-pathfinding + kryty)
```

### Tik (volá `MatchSession.tick` → `ai.update(dt)`, pevně 1/60 s)

1. `nav.update(dt)` — vypršení dočasných blokací navmeshe.
2. Pro každého živého bota:
   - **vnímání zrakem** v jeho časovém okně (10 Hz, okna rovnoměrně rozložená mezi boty),
   - útlum paměti,
   - **rozhodnutí** (4,5 Hz ± 0,04 s; okamžitě po události: zásah, změna kontroly oblasti, smrt cíle, nové kolo),
   - **provedení** (každý tik): pohyb, pohled/míření, palba, přebití → `cmd` ve **stejném formátu jako hráč** →
     `combatant.applyCommand(cmd, dt)`.
3. Mrtvé boty krokuje `CombatantManager.stepUndriven` (AI jim nic neposílá).

Sluch a zásah přicházejí z událostí (`weapon:fired`, `footstep`, `combatant:damaged`), zapomínání z
`combatant:died` / `combatant:spawned`; `zone:control_changed` a `round:started` vynutí nové rozhodnutí,
`reset()` (nové kolo) vymaže paměti, cesty, rezervace krytů, blokace i týmové nároky.

### Napojení na herní integraci

- `createAISystem({ combatants, world, nav, cover, events, match, config })` — `world` = `WorldQuery`
  (`raycastStatic`, `lineOfSight`). Když `nav`/`cover` jsou `null` (tak je předává `MatchSession`), AI si navmesh a kryty
  vezme ze zapečeného registru podle `config.levelId` (`navRegistry.generated.js`, do balíku se dostane staticky, tedy
  synchronně i v Node testech). `config.tuning` = přepis `ai.json` (JSON sloučení; jen testy / ladění).
- Aktivní oblast: `config.session.activeZone()`, kontrola oblasti `match.round.zone.controller` (veřejné údaje z HUD).
- Rychlost otáčení bota: jediný zdroj je `ai.json turnRateDegPerSec`; `addBot` ji zapíše do `combatant.turnRateDegPerSec`,
  kterou `Combatant.applyCommand` znovu vynucuje (AI i kontroler tedy omezují stejnou hodnotou).
- Palba jde přes `WeaponSystem` hráče i botů stejně: hitscan z oka + ověření od ústí (D8). AI navíc před stiskem
  spouště ověřuje stejné dva úseky (oko → ústí, ústí → cíl), aby zbytečně nestřílela do zdi.

## 3. Navmesh a body krytu (build)

`npm run build` = `node tools/bake_navmesh.mjs && node tools/build.mjs`; samostatně `npm run bake:nav`
(`--force` přepeče, `--check` jen zkontroluje aktuálnost, `--level <id>` jen jednu úroveň). Pečou se všechny úrovně
v `src/data/*.json`, které mají blok `match` nebo `nav` (teď `ai_arena` a `test_range`). Mezipaměť: hash skutečné kolizní
geometrie + dat úrovně (`match`, `nav`, `aiTest`) + zdrojového kódu nástroje.

| Parametr (Recast, solo navmesh) | Hodnota |
| --- | --- |
| buňka `cs` / `ch` | 0,05 m / 0,05 m |
| poloměr agenta | 0,35 m (7 buněk) |
| výška agenta | 1,80 m (36 buněk) |
| max. stoupnutí | 0,40 m (8 buněk) |
| max. sklon | 45° |
| `maxEdgeLen` / `maxSimplificationError` | 240 / 1,1 |
| `minRegionArea` / `mergeRegionArea` | 16 / 40 |
| `detailSampleDist` / `MaxError` | 6 m / 1 (hrubé záměrně: rovné podlahy a rampy schodů) |

Postup: kolizní trojúhelníky úrovně (stejná geometrie jako BVH kolizního světa, **bez** solidů s `"nav": false`) →
Recast → trojúhelníky navmeshe → `Pathfinding.createZone` (three-pathfinding 1.3.0) → **hlavní skupina** = souvislá část,
ve které leží všechny spawny, středy oblastí a testovací body AI (jinak build **selže**, např. „spawn nedosažitelný“).
Střechy a vršky kontejnerů jsou samostatné ostrůvky mimo hlavní skupinu.

**Body krytu z geometrie** (vše v `tools/bake_navmesh.mjs`):
1. hraniční hrany hlavní skupiny navmeshe (hrana trojúhelníku bez souseda) vzorkované po 0,5 m; hrany na schodech se přeskakují;
2. vodorovný paprsek ve výšce 0,5 m ven od navmeshe (dosah 0,75 m) musí narazit na svislou plochu překážky;
   normála krytu = normála té plochy (**od překážky**); solidy z `nav.coverExcludeSolids` (hranice arény) se vynechají;
3. výška překážky paprsky v 0,3 / 0,6 / 0,9 / 1,1 / 1,3 / 1,5 / 1,7 / 1,9 / 2,1 m: vršek < 0,9 m → není kryt;
   0,9–1,7 m → **low** (skrčený je krytý, ve stoje střílí přes); ≥ 1,7 m → **high** (kryje i oko ve stoje);
   blokováno pod parapetem, volno nad ním a zase blokováno nad otvorem → **okno**;
4. u high krytu strana vyklonění (vlevo/vpravo, zda překážka 0,6 m vedle končí) a **pozice vyklonění** 0,8 m do strany
   (jen když leží na navmeshi a vede k ní volná úsečka);
5. rozestupy (≥ 0,7 m mezi libovolnými, ≥ 1,1 m se stejným směrem), posun 2 cm dovnitř navmeshe a kontrola, že bod po
   zaokrouhlení leží v hlavní skupině (**dosažitelnost**).

**Za běhu** (čistý JS): zóna ve formátu three-pathfinding se načte do `Pathfinding` (`setZoneData`) a do `NavMeshData`.
Hledání cesty je **vlastní metrické A\*** (cena hrany = vzdálenost středů portálů, heuristika = přímá vzdálenost,
násobitele ceny a zablokované trojúhelníky) a **string pulling** (simple stupid funnel s explicitním určením levé/pravé
strany portálu). Důvod: A\* v three-pathfinding 1.3.0 počítá cenu 1 za polygon s kvadratickou heuristikou (není to nejkratší
cesta) a neumí vyloučit zablokované oblasti. `findPath` z three-pathfinding slouží testům jako reference (naše cesty jsou
stejně dlouhé nebo kratší, tabulka v oddílu 11). Rohy cesty se odsunou o 0,2 m od překážky, pokud to navmesh dovolí.

## 4. Vnímání a paměť (AI-01)

**Zrak** (každý bot 10× za sekundu, okna rozložená mezi boty): dosah 110 m, zorné pole 130° (centrální 70°, v periferii
detekce × 0,4). Paprsky `worldQuery.lineOfSight` z oka bota ke **třem bodům uvnitř zásahových tvarů** nepřítele
(hlava 0,3, hrudník 0,4, pánev 0,3 — váhy viditelnosti; statická geometrie i jiná těla blokují). Úroveň detekce roste
rychlostí `viditelnost × periferie × (0,8 v dřepu) × (1,25 při pohybu ≥ 2,5 m/s) / T(d)`, kde `T(d)` je doba detekce
plně viditelného, stojícího cíle: 0,2 s do 8 m, lineárně 0,9 s ve 40 m, dál roste až do dosahu. **Spatřen** = úroveň ≥ 1
(nenulová reakční doba). Úroveň ≥ 0,35 dá jen **záblesk**: přibližnou polohu (chyba 1 m + 5 % vzdálenosti) a otočení
tím směrem; na záblesk bot 1,2 s jen hledí (detekce se může dokončit), teprve pak jde pátrat. V průchodu, ve kterém cíl
poprvé vidí, se započítá jen polovina intervalu vnímání (cíl se objevil někde mezi průchody) — detekce tak nikdy nepřijde
dřív než konfigurovaná doba (dříve až o 0,1 s dřív, oprava 2026-09-27).

**Sluch** (události): výstřel dosah 90 m × hlasitost, kroky 16 m × hlasitost (sprint 1,0, běh 0,55, chůze 0,25, dřep 0,15);
přes statickou geometrii dosah × 0,55. Poloha je **vždy přibližná**: náhodná chyba v kruhu o poloměru
`(1,5 m + 0,08 × vzdálenost) × (1,6 přes zeď)`. Výstřel, který proletí do 2,5 m od bota („šum kulky“), znamená „pod palbou“ —
jen když střela opravdu doletěla tak daleko (zastaví se o první zeď / tělo; dříve se počítala 150 m dráha bez ohledu na zásah
a 25 % „průletů“ šlo skrz zdi). Zvuky spoluhráčů se ignorují.

**Zásah** (`combatant:damaged`): použije se **jen směr střely** `fromDir` s chybou ±15°; vzdálenost se odhadne (20 m),
nebo se ponechá existující odhad ze sluchu, pokud leží zhruba tím směrem. Pole `attackerPosition` z události AI **nečte**.

**Paměť** (na nepřítele): poslední známá poloha nohou, čas, vnímaná rychlost (z rozdílu dvou pozorování), zdroj,
důvěra 1 → klesá (16 s po spatření, 9 s po zvuku; během aktivního pátrání 4× pomaleji), při 0 se záznam zapomene.
Predikce = poslední poloha + vnímaná rychlost × nejvýš 0,8 s. **Záznam mění jen podnět** (spatření, zvuk, zásah);
bez podnětu se poloha nikdy nepřepíše skutečnou polohou (test AI-01d kontroluje každý tik).
Smrt nebo respawn nepřítele → okamžité zapomenutí u všech botů.

## 5. Rozhodování (utility, ~4,5 Hz)

| Úkol | Skóre | Co bot dělá |
| --- | --- | --- |
| `engage` | 0,9, když cíl vidí | zastaví / v dřepu nad 15 m / pod 12 m úkroky; když oblast potřebuje tým a není pod palbou (cíl > 15 m), **postupuje dál k oblasti** a střílí za pohybu |
| `cover` | 0,72 (+0,22 pod palbou, +0,08 při přebíjení / málo munice) když vidí nebo je pod palbou a není kryt; 0,86 při přebíjení s nepřítelem poblíž; 0,92 pokud už je v dobrém krytu a boj trvá; −0,3 po 13 s v krytu | rezervuje kryt, který chrání proti odhadované hrozbě (a z něhož lze střílet), jde k němu; cyklus schovat / vyklonit (low: dřep / stoj, high: přesun na pozici vyklonění); při obejití nebo po čase jiný kryt |
| `search` | 0,45 + 0,35 × důvěra (−0,25, když je oblast naléhavá a stopa > 25 m) | jde na poslední známou / predikovanou polohu (posledních 8 m chůzí), rozhlíží se 3 s, pak to vzdá a záznam zapomene (max. 16 s) |
| `objective` | 0,5 (0,3 bez oblasti) | pozice v aktivní oblasti: volný kryt uvnitř, chránící proti směrům nepřátelských spawnů, jinak náhodný bod navmeshe; rozestup od spoluhráčů ≥ 3 m (TeamBoard); po 9–16 s změna pozice; rozhlížení po přístupech |

Aktuální úkol má +0,07 (hystereze). Bez oblasti (trénink, testy v „hlídacím režimu“) bot drží místo.
Konec kola → `idle` (a zámek výsledků stejně nedovolí střílet). **Odpočet před kolem** (`pre_round`) → `idle` ve spawnu
(vnímání a sebeobrana zůstávají), všichni vyrazí na signál `round:started` (dříve boti běželi k oblasti a zabíjeli se už
během „Start za 5 s“).

**Tlak oblasti (AI-04, 2026-09-27):** když tým nemá v oblasti, kterou nedrží, nikoho déle než `objective.pressureGrace`
(4 s), roste jeho tlak 0 → 1 za `pressureRamp` (16 s); drží-li oblast nepřítel, je tlak aspoň `pressureEnemyHolds` (0,5).
Boti toho týmu mimo oblast: `objective` + `pressureWeight` × tlak (až 0,92); kulky létající kolem („pod palbou“ bez zásahu)
je v krytu drží úměrně méně (skutečný zásah za posledních 2,5 s ano); dobrý kryt opouštějí dřív (max. doba v krytu
× (1 − 0,6 × tlak)) a nový kryt vybírají blíž k oblasti (skok od krytu ke krytu); pátrání se tlakem potlačí; `engage`
s postupem pokračuje i pod palbou, když tlak ≥ 0,5 a bot není zasažen ani nepřítel není blíž než 15 m. Držitel oblasti
nevyráží pátrat po kontaktu dál než 6 m za okraj oblasti. Klidné úkoly (`search` ↔ `objective`) se nepřepínají dřív než po
`tick.calmTaskMinTime` (2 s), dokud jsou proveditelné, a nový (přibližný) zvukový odhad do 3 m od cíle pátrání trasu
nemění — jinak bot přepínal mezi dvěma cestami kolem budovy a přešlapoval na místě.

**Palba (vrstva nad každým úkolem, každý tik):** cíl je vidět (nebo byl vidět před ≤ 0,25 s) → sledování s modelem chyby;
první výstřel až po **reakční prodlevě** 0,25–0,45 s od spatření (znovuzachycení do 1,5 s: poloviční). Spoušť se stiskne,
když pohled dohnal zamýšlený směr (±2,5°, zblízka 0,45 m), **ústí má volnou čáru** (oko → ústí i ústí → cíl, pro aktuální
i příkazový pohled a posun o jeden tik), žádný spoluhráč není blíž než 0,75 m (+ rezerva na zákluz) od čáry střelby.
Dávky podle vzdálenosti (tabulka v oddílu 10); po dávce pauza — i po dávce **přerušené** (ztráta cíle, spoluhráč v čáře,
blokované ústí), pokud z ní už vyšla rána; dříve na přerušenou dávku hned navázala další a vznikaly dávky 8–9 ran.
Spoluhráč v čáře střelby: kontroluje se celá dráha střely až k první zdi (i za cílem), s rezervou 0,75 m + vzdálenost ×
(kop + 2σ chyby míření); spoluhráč blíž než 0,9 m (těla se překrývají) palbu vždy zastaví.
Blokované ústí > 0,6 s → úkrok na stranu, kde se čára uvolní.
Přebití: prázdný zásobník, nebo < 34 % a 2 s bez kontaktu a ne pod palbou; během přebíjení, se zamčenou zbraní
(výměna, sprint, smrt) nebo při sprintu se **nikdy nestřílí**.

## 6. Míření (AI-03)

Bot otáčí pohled **přes příkaz** (`cmd.yaw/pitch`) nejvýš 300°/s (pitch 220°/s) — 5° za tik; otočka o 180° trvá ≥ 0,6 s.
Chyba míření je plynulý náhodný proces (Ornstein–Uhlenbeck, korelační čas 0,35 s, stacionární rozptyl 1) násobený

```
sigma [°] = (0,9 + 0,12 × d/10 + 0,45 × boční rychlost cíle [m/s] + 1,5 × vlastní rychlost / 3,5)
            × (0,8 v dřepu) × (2,6 → 1 během 1,1 s sledování)
```

Nový cíl začíná plnou chybou (stav procesu z rozdělení N(0,1)). Test měří skutečnou úhlovou chybu výstřelů: RMS 0,82°/0,98°
(yaw/pitch) proti modelu 0,94° ve 20 m, 2,27°/2,21° proti 2,26° v 10 m (se strafováním). Žádný aimbot: přesnost je jen tento model.

## 7. Pohyb (AI-02)

- **Cesta**: metrické A\* po navmeshi + funnel; průjezd bodem v okruhu 0,4 m (cíl 0,5 m); obnova cesty po 2,5 s nebo při
  posunu cíle > 1,5 m. Sprint na dlouhých úsecích bez hrozby (pohled se pak drží směru cesty, jinak kontroler sprint nedovolí).
- **Vyhýbání**: odpuzování těl do 1,4 m (váha 1,6) + úkrok do strany pro těla v koridoru 2,2 m před botem (šířka 0,9 m);
  strana podle polohy druhého, při čelním střetu podle parity indexu. Kapsle se navzájem fyzicky nesrážejí — odstup drží AI:
  **bot nikdy nejde do těla** blíž než `movement.contactRadius` (0,85 m) — složka pohybu směrem k tělu se odečte (obchází,
  stojí nebo couvá), platí pro cestu, úkroky i couvání; odpuzování působí i na bota bez cíle (drží místo a střílí), takže
  spoluhráči v boji nestojí v sobě.
- **Zaseknutí**: chce jet, ale za 1,5 s se posunul < 0,3 m (nebo se posunul jen podél stěny bez postupu po cestě) → událost.
  Druhý detektor (kotva): chce jet, ale 3 s neopustí kruh 0,75 m — zachytí bota, kterého dav v úzkém místě posouvá sem a tam.
  Po couvnutí / čekání se okno měří znovu od konce manévru; už zaseknutý bot (nebo nová událost do 1,5 m od předchozí
  do 8 s) se znovu vyhodnotí po 1,0 s. Obnova (**nikdy teleport**):
  1. **tělo v cestě** (do 1,3 m) a před botem není překážka neznámá navmeshi → první událost zácpy: nižší priorita (vyšší
     index; hráč má vždy přednost) ustoupí na volnější stranu a 1,2 s počká, v úzkém místě (dveře, ulička, na straně < 0,6 m)
     místo toho couvne od těla; přednost se v jedné zácpě uplatní jen jednou; **druhá událost ve stejné zácpě nebo na stejném
     místě → couvnutí a nový cíl**; stojí-li tělo v cestě, trasy bota se jeho okolí 6 s vyhýbají (cena ×6, jen tento bot);
     nikdy se kvůli tělům neblokuje navmesh;
  2. **překážka, kterou navmesh nezná** (solid s `"nav": false`, např. zátaras, nebo nic z dat úrovně) před dalším bodem
     cesty → **tvrdá** blokace jejího půdorysu na 30 s pro všechny a nová trasa; opakované zaseknutí u známé překážky
     na stejném místě bez těl → **měkká** blokace 1,1 m před botem. Měkká blokace nikdy nikoho neodřízne: když přeruší
     všechny cesty, trasa ji ignoruje (kromě vlastní). Dříve blokoval disk 1,1 m kolem *jakékoli* stěny, o kterou dav bota
     přitlačil — 10 velkých trojúhelníků u východu ze spawnu týmu Charlie odřízlo spoluhráče na 30 s (412 selhání cesty);
  3. jinak (zachycení o roh, opakované selhání) → 0,6 s couvnutí, nová cesta a rozhodovací vrstva zvolí jiný cíl.
  Smrt bota uzavře otevřenou událost (`recoveredBy: died`, bez „obnovy“ trvající celou dobu smrti).
- **Mapa nebezpečí týmu**: kde spoluhráč padl, je 30 s cesta dražší (do 5 m, násobitel až 4) — dveře, které se staly
  „vražednou zónou“, tým chvíli obchází (ulička, průchod).

## 8. AI aréna (`src/data/ai_arena.json`)

Graybox 71 × 71 m (hrací plocha ±35,5 m), souřadnice three.js (Y nahoru, sever = −Z), schéma jako `test_range.json`
(`solids`, `signs`, `banners`, `dummies`, `markers`) + `match` (schéma herní integrace), `nav` a `aiTest`.

| Prvek | Popis |
| --- | --- |
| Oblast **Střed** `arena_center` | válec r 6 m, výška 2,5 m, uprostřed sloup 1,2 × 1,2 × 2,2 m a tři nízké bloky; na okraji tři vysoké a dva nízké kryty |
| Kandidáti oblasti | `arena_house` (přízemí domu, r 3,6 m), `arena_yard` (severní dvůr, r 5 m) — testovací, nejsou férové; AI testy vynucují `arena_center` přes `rulesPatch` |
| Spawny | 3 × 8 bodů po 2,5 m v krytech z 2,6 m vysokých zdí se zalomeným východem (zástěna), takže je nepřítel zvenku nevidí (predikát spawnu); vzdálenost ke středu ~28–31 m |
| Dvoupatrový dům | 10 × 8 m, zdi 0,25 m, patra 3,0 m, dveře 1,2 × 2,1 m na jihu a severu, okna v přízemí (parapet 1,0 m) i v patře, schodiště 17 × 0,176 m podél východní zdi, zábradlí u schodiště, střecha; stůl a bedna jako vnitřní kryt |
| Zeď z = 17 | odděluje jih (tým Alfa); průchody: dům, **ulička** 1,5 m × 10 m (x 12,1–13,6), **otevřený průchod** 4 m (x −22 … −18) |
| Severní dvůr | zeď z = −24 se dvěma mezerami: **K1** (x −1…1) je zavřená zátarasem `yard_barricade` s `"nav": false` (kolizní, ale navmesh o něm neví — test zablokované cesty), **K2** (x 6…8) je volná |
| Kryty | nízké (1,0–1,1 m) a vysoké (2,2–2,6 m) bloky na trasách všech týmů; trasa Bravo kontejnery, trasa Charlie jen nízké kryty (otevřený pruh) |
| `aiTest` | polohy pro testy: pruh pro zrak 10–50 m, zeď pro AI-01b/c, kontejner pro AI-01d, zátaras, body v patře, 17 tras (dveře, schody, ulička, průchod, střed, K2, sever) |

Navmesh arény: 668 trojúhelníků v 11 skupinách, hlavní skupina 648 trojúhelníků / 4 588 m², pečení ~1,5–2 s.

## 9. Ladění: `window.__IV.ai` a 3D překryv

AI se do `window.__IV` připojí sama při prvním `update` (hra na tom nezávisí). Metody:

| Volání | Význam |
| --- | --- |
| `getDebug()` | celý stav: navmesh (blokace, statistiky), rezervace krytů, aktivní oblast, na bota úkol + důvod + skóre, cíl, vnímání (vidí / úrovně detekce / slyšené zvuky / upozornění / pod palbou), paměť (poslední známé polohy, stáří, důvěra, zdroj), deník změn paměti, reakční časovač, model chyby, stav palby (dávka, pauza, důvod neodpálení), zbraň, kryt (fáze), pozice v oblasti, pátrání, cesta a události zaseknutí, metriky |
| `bot(id)`, `brief(id)`, `memory(id)`, `positions()` | jeden bot / malý stav / paměť / polohy všech |
| `setOverlay(true/false)` | 3D překryv: cesty (barva týmu), směr pohledu (bílá), poslední známé polohy (zelená = vidí, žlutá = slyšel / starší, jen důvěra ≥ 0,3), rezervované kryty (azurová s normálou), zablokované oblasti navmeshe (purpurová) |
| `setGuardMode(on)` | testy: ignorovat oblast (boti drží místo) |
| `commandMove(id, [x,y,z])`, `clearCommand(id)` | testy: skriptovaný přesun (bot vnímá, ale nebojuje) |
| `setLookHint(id, yawDeg, s)` | testy: kam se nečinný bot dívá |
| `navDebug()`, `coverPoints()` | navmesh a body krytu |

`ai.json → debug.overlay: true` zapne překryv automaticky. Herní `__IV.getAIDebug()` vrací totéž co `getDebug()`.

## 10. Laditelné hodnoty (`Shared/config/ai.json`)

Časy v s, vzdálenosti v m, úhly ve °. Přepis pro testy: `createAISystem({..., config: { tuning: {...} } })`.

| Klíč | Hodnota | Význam |
| --- | --- | --- |
| `turnRateDegPerSec` / `pitchRateDegPerSec` | 300 / 220 | max. rychlost otáčení (zapisuje se i do Combatantu) |
| `tick.perceptionHz` / `decisionHz` / `decisionJitter` | 10 / 4,5 / 0,04 | frekvence vnímání a rozhodování |
| `vision.range` / `fullDetectionRange` / `nearRange` | 110 / 40 / 8 | dosah zraku; do `fullDetectionRange` plná rychlost detekce |
| `vision.fovDeg` / `centralFovDeg` / `peripheralFactor` | 130 / 70 / 0,4 | zorné pole, centrální pole, násobitel v periferii |
| `vision.detectTimeNear` / `detectTimeFar` | 0,2 / 0,9 | doba detekce plně viditelného cíle v 8 m / 40 m |
| `vision.detectDecayPerSec` | 1,0 | pokles úrovně detekce za s, když cíl není vidět |
| `vision.crouchFactor` / `movingSpeed` / `movingFactor` | 0,8 / 2,5 / 1,25 | skrčený cíl hůř, pohyb nad 2,5 m/s lépe |
| `vision.minVisibility` / `bodyPoints` | 0,15 / hlava 0,3, hrudník 0,4, pánev 0,3 | min. viditelný podíl těla, váhy bodů |
| `vision.glimpseLevel` / `alertTurnTime` | 0,35 / 3,0 | záblesk (přibližná poloha), jak dlouho se dívá k podnětu |
| `hearing.gunshotRange` / `footstepRange` | 90 / 16 | dosah sluchu (× hlasitost události) |
| `hearing.occlusionFactor` | 0,55 | dosah přes zeď |
| `hearing.errorBase` / `errorPerMeter` / `occludedErrorMult` | 1,5 / 0,08 / 1,6 | chyba odhadu polohy zvuku |
| `hearing.confidenceGunshot` / `confidenceFootstep` | 0,6 / 0,45 | důvěra záznamu ze zvuku |
| `hearing.whizRadius` / `ignoreFriendly` | 2,5 / true | průlet kulky kolem = pod palbou; zvuky spoluhráčů ignorovat |
| `damage.directionErrorDeg` / `guessDistance` / `confidence` / `underFireTime` | 15 / 20 / 0,55 / 2,5 | zásah: chyba směru, odhad vzdálenosti, důvěra, doba „pod palbou“ |
| `memory.decayTimeSeen` / `decayTimeHeard` | 16 / 9 | za jak dlouho důvěra klesne z 1 na 0 |
| `memory.velocityExtrapolation` | 0,8 | max. doba predikce z vnímané rychlosti |
| `memory.searchMinConfidence` / `searchRadius` / `searchLookTime` / `searchMaxTime` | 0,12 / 4 / 3 / 16 | pátrání: min. důvěra, okruh příchodu (× 0,4), rozhlížení, max. délka |
| `memory.searchingDecayFactor` / `glimpseWatchTime` / `forgetAfterSearch` | 0,25 / 1,2 / true | útlum při pátrání, jen hledět na záblesk, zapomenout po neúspěchu |
| `aim.baseErrorDeg` / `distanceErrorDegPer10m` | 0,9 / 0,12 | chyba míření (sigma) |
| `aim.targetSpeedErrorDegPerMps` / `ownMoveErrorDeg` / `crouchErrorFactor` | 0,45 / 1,5 / 0,8 | vliv pohybu cíle, vlastního pohybu, dřepu |
| `aim.initialErrorMult` / `settleTime` / `noiseCorrelation` / `aimHeightOffset` | 2,6 / 1,1 / 0,35 / 0 | usazování míření, korelace šumu, výška zaměření |
| `combat.reactionDelayMin` / `reactionDelayMax` | 0,25 / 0,45 | reakční prodleva před 1. výstřelem (musí být > 0) |
| `combat.fireConeDeg` / `fireConeMinMeters` | 2,5 / 0,45 | kdy smí stisknout (pohled dohnal zamýšlený směr) |
| `combat.maxEngageRange` / `continueFireAfterLostSight` / `adsRange` | 100 / 0,25 / 18 | dosah palby, dostřelení po ztrátě, míření přes mířidla nad 18 m |
| `combat.bursts` | ≤12 m: 4–7 ran, pauza 0,18–0,4; ≤30 m: 3–5, 0,3–0,6; ≤60 m: 2–3, 0,45–0,8; dál 1–2, 0,6–1,0 | dávky podle vzdálenosti |
| `combat.reloadBelowFraction` / `safeReloadNoContactTime` | 0,34 / 2,0 | přebití „v bezpečí“ |
| `combat.muzzleCheck` / `muzzleStepOutAfter` | true / 0,6 | kontrola ústí před stiskem, úkrok při blokovaném ústí |
| `cover.searchRadius` / `minThreatDistance` / `threatConeDeg` | 14 / 5 / 75 | výběr krytu |
| `cover.maxTimeInCover` / `peekTime*` / `hideTime*` / `teammateSpacing` | 13 / 1,4–2,6 / 0,7–1,5 / 2,5 | změna krytu, cyklus vyklonění, rozestup |
| `objective.zoneMargin` / `holdReposition*` / `scanInterval*` / `teamSpacing` | 0,8 / 9–16 / 1,6–3,4 / 3,0 | pozice v oblasti |
| `movement.arriveRadius` / `waypointRadius` / `sprintMinDistance` | 0,5 / 0,4 / 10 | sledování cesty |
| `movement.separationRadius` / `separationWeight` / `avoidLookAhead` / `avoidRadius` | 1,4 / 1,6 / 2,2 / 0,9 | vyhýbání |
| `movement.repathInterval` / `goalMoveRepath` | 2,5 / 1,5 | obnova cesty |
| `stuck.window` / `minProgress` | 1,5 / 0,3 | detekce zaseknutí |
| `stuck.blockRadius` / `blockTtl` / `backoffTime` / `teammateWaitTime` / `maxRecoveries` | 1,1 / 30 / 0,6 / 1,2 / 4 | obnova |
| `stuck.anchorRadius` / `anchorWindow` / `recheckWindow` | 0,75 / 3,0 / 1,0 | detektor kotvy, rychlejší opakovaná kontrola |
| `movement.contactRadius` / `bodyAvoidRadius` / `bodyAvoidTime` / `bodyAvoidCost` | 0,85 / 1,5 / 6 / 6 | nejít do těla; vyhnout se stojícímu tělu v cestě |
| `objective.pressureGrace` / `pressureRamp` / `pressureWeight` / `pressureEnemyHolds` / `pressureCoverTimeCut` / `holderSearchLeash` | 4 / 16 / 0,42 / 0,5 / 0,6 / 6 | tlak oblasti |
| `tick.calmTaskMinTime` / `memory.searchGoalKeepRadius` | 2,0 / 3,0 | bez přešlapování mezi pátráním a oblastí |
| `danger.duration` / `radius` / `weight` / `maxMultiplier` | 30 / 5 / 1,5 / 4 | mapa nebezpečí týmu |
| `debug.overlay` | false | zapnout 3D překryv automaticky |

## 11. Naměřené hodnoty

Měřeno na skutečné herní integraci (`MatchSession`, `Combatant.applyCommand`, `WorldQuery`, hitscan s ověřením ústí,
jádro `Match`) v AI aréně: v Node (`tests/unit/ai_*.test.mjs`, deterministicky se semenem) a v sestavené hře v headless
Chromiu s vypnutým vykreslováním (`tests/e2e/05_ai.test.mjs`). Datum 2026-09-26 (integrace 2026-09-27 viz pododdíl níže). Poslední úplný běh: viz `STATUS.md`.

### AI-01 — zrak, sluch, paměť

| Situace | Konfigurace | Naměřeno |
| --- | --- | --- |
| detekce viditelného hráče 10 m | 0,244 s | 0,283 s |
| 20 m | 0,463 s | 0,483 s (prohlížeč 0,450 s) |
| 30 m | 0,681 s | 0,683 s |
| 40 m | 0,900 s | 0,983 s (vnímání běží po 0,1 s) |
| tichý hráč za zdí (6 m), 20 s | nesmí být detekován | 0 detekcí, paměť hráče nikdy neobsahovala (201 aktualizací vnímání, 603 paprsků) |
| jeden výstřel za zdí (6 m) | chyba ≤ (1,5 + 0,08 d) × 1,6 = 3,2 m | chyba 1,67 m (prohlížeč 2,50 m), zdroj „sluch“; bot obešel zeď, došel na 0,89 m k odhadu, rozhlédl se a po 12,9 s to vzdal (`not_found`), záznam zapomenut |
| ztráta kontaktu, hráč se tiše přesune | poslední známá poloha se nesmí měnit | poloha (−16; 0; −7,5) beze změny, 0 aktualizací bez podnětu (Node i prohlížeč) |
| smrt / respawn cíle | zapomenout | zapomenuto v tomtéž tiku; po respawnu neznámý, dokud ho znovu nevnímá |

### AI-02 — cesty a vyhýbání

| Měření | Výsledek |
| --- | --- |
| 17 botů současně po 17 trasách (dveře domu, schody do patra, ulička, průchod, střed, K2, sever) | 17/17 v cíli, čas 3,4–13,4 s (medián 6,3 s); prohlížeč 17/17, max. 12,0 s |
| zaseknutí při přechodu | 1 událost (blokace + nová cesta), obnova 0,45 s; nejdelší doba bez postupu 3,5 s; prohlížeč 0 událostí |
| teleport | max. posun za tik 0,0969 m (limit sprint 5,8 m/s × 1/60 + 0,02 = 0,1167 m), svisle max. 0,18 m (schody) |
| dva boti na jednom místě (< 0,45 m) | nejdelší souvislý překryv 0,15 s |
| zablokovaná cesta (zátaras K1 mimo navmesh) | bot dorazil k zátarasu v 1,30 s, zaseknutí rozpoznáno v 2,83 s → **1,53 s** (limit 3 s), obnova 0,47 s, cíl přes K2 v 7,12 s; druhý bot později rovnou přes K2 (4,48 s, bez zaseknutí); prohlížeč 1,53 s |
| rezervace krytu | výlučná (test CoverService); v zápasech 0 s dvou stojících botů na jednom krytu |
| cesty proti referenci three-pathfinding | stejné nebo kratší (+ ≤ 0,9 m za odsunutí rohů), např. schody 28,4/27,5 m, střed 54,9/59,4 m |

### AI-03 — boj

| Měření | Výsledek |
| --- | --- |
| reakce (umístění do výhledu → 1. výstřel), 4 pokusy | 10 m 0,54 s, 20 m 0,79 s, 40 m 1,30 s (vše v okně detekce + 0,25–0,45 s + dotočení); prohlížeč 20 m 0,88 s; medián v zápase 0,50–0,57 s (100 vzorků) |
| zásahovost vs. model (3 × 25 s, stojící cíl) | 10 m (strafuje, 8,6 m): 0,331 vs. model 0,317; 20 m: 0,313 vs. 0,360; 40 m: 0,104 vs. 0,112; prohlížeč 20 m ≈ 0,36 |
| citlivost na data | 3× `aim.baseErrorDeg` → zásahovost ve 20 m 0,322 → 0,085 |
| dávky | vždy ≤ max. pásma (10 m: 4–7, 20 m: 3–5, 40 m: 2–3), většina v pásmu |
| palba při přebíjení | 0 (23 přebití v testu, 0 v zápasech, 519 tiků přebíjení v prohlížeči) |
| otáčení | max. 5,0°/tik (= 300°/s), otočka o 150° za 0,50 s |
| pravidlo ústí | oko vidí cíl, ústí ve zdi: výstřel `blocked: eye-to-muzzle`, 0 poškození; AI držela palbu 0,8 s, pak úkrok a 11 výstřelů, 0 s blokovaným ústím; v zápasech 0 z 7 191 ran s blokovaným ústím (dřívější běhy do 0,15 %), **0 zásahů skrz zeď** |

### AI-04 — tým a cíl

| Měření | 180 s, hráč nečinný | 120 s bez hráče | prohlížeč 120 s, hráč nečinný |
| --- | --- | --- | --- |
| skóre Alfa/Bravo/Charlie | 1 / 27 / 16 | 1 / 13 / 6 | 1 / 20 / 4 |
| čas týmu v oblasti (s) | 15,4 / 81,3 / 48,3 | 11,9 / 45,4 / 20,5 | 13 / 59,5 / 17,5 |
| zabití | 39 / 51 / 46 | 23 / 38 / 29 | 27 / 34 / 30 |
| stavy oblasti / kontroloři | prázdná, držená, sporná / 0, 1, 2 (60 změn) | prázdná, držená, sporná / 0, 1, 2 (47 změn) | prázdná, držená, sporná / 0, 1, 2 |
| cíl = spoluhráč, spojenec → hráč, friendly fire | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| zaseknutí (obnoveno) | 16 (vše, max. 1,7 s) | 15 (vše, max. 5,3 s) | — |
| spoluhráči stojící < 1 m od sebe | 1,3 % vzorků | 1,6 % | — |
| nové rozhodnutí po změně kontroly oblasti | všichni v dalším tiku | všichni | — |
| rány do zdi s blokovaným ústím / zásahy skrz zeď | 0 z 4 358 / 0 | 0 z 2 833 / 0 | — |
| medián reakce v zápase | 0,50 s | 0,57 s | — |

Přepočet úkolů po smrti (kryt uvolněn, paměť smazána, všichni zapomněli mrtvého), po respawnu (nový mozek, hned
rozhoduje) a po novém kole (rezervace, blokace, paměti, cesty smazány; ≥ 12 botů do 2 s míří k oblasti) ověřuje test.

### Integrace: skutečná kola se 3 a 17 boty (2026-09-27)

Skutečná kola v AI aréně (`MatchSession` + AI + hitscan + jádro), nezávislý pozorovatel mimo projekt (skóre, oblast,
zabití, respawny, zaseknutí podle polohy, posun za tik, otáčení, rány / zásahy / zdi, přebíjení, překryvy těl, kryty),
v Node (8 semen × 180 s, plná kola) a v sestavené hře v Chromiu s vypnutým vykreslováním (`simulate`, plné kolo časově
zrychlené přes skutečnou smyčku ×10). Hráč nečinný ve spawnu (tým Alfa má tak o jednoho aktivního bojovníka méně).

| 17 botů, 8 semen × 180 s (Node) | před opravami | po opravách |
| --- | --- | --- |
| nejdelší zaseknutí (chce jet, neopustí 0,75 m) | 5,62 s | 2,92 s |
| nejdelší „plazení“ (6 s chce jet, < 1,5 m) | 9,95 s | 6,77 s |
| nejdelší obnova detektoru AI | 6,05 s | 2,38 s |
| selhání cesty „částečná cesta končí u bota“ | 412 / 128 (semena 1, 8) | ≤ 4 |
| dva boti na jednom místě (< 0,45 m) | až 3,45 s | ≤ 0,5 s |
| rány do spoluhráče (FF vypnutý, zablokováno) | 4 | 0 |
| týmy, které byly v oblasti (dvůr, semena 2–5) | „1“, „1“, „12“, „12“ | všechny tři ve všech semenech |
| nejdelší čekání na respawn | 21 s | 12 s |
| teleporty / palba při přebíjení / zásah skrz zeď / otočka > 5°/tik | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| cena tiku (CPU, 17 botů, Node) | 1,09–1,66 ms | 1,06–1,57 ms |

| Plné kolo 17 botů (Node) | před | po |
| --- | --- | --- |
| Dům (semeno 1) | 94/7/4 časem, oblast prázdná 37 % | 100/15/8 cílem v 475 s, prázdná 21 % |
| Dvůr (semeno 4) | 0/7/4 časem, prázdná 87 %, Alfa nikdy v oblasti | 1/31/24 časem, prázdná 70 %, všechny týmy oblast držely |
| Střed (semeno 7) | 9/85/68 časem, prázdná 26 %, spor 45 s | 16/61/41 časem, prázdná 27 %, spor 83 s |

Dalších 9 plných kol (Node, 6× Střed, 3× podle semene) i e2e v prohlížeči: vždy vítěz (cílem nebo časem), všechny tři týmy
oblast držely, telemetrie (poloměr 1 m) nejdelší zaseknutí 2,9–4,65 s, žádný teleport ani chyba. Prohlížeč (vypnuté
vykreslování): 3 boti 0,27 ms/tik, 17 botů 0,9–1,1 ms/tik (54–66 ms na simulovanou sekundu), plné kolo časově zrychlené
10/72/38 (Bravo časem), zaseknutí max 3,3 s. Nezávislé ověření AI-01 (14/14), AI-02 (11/11, čelní proudy 17 botů dveřmi
domu, uličkou 1,5 m, po schodech a mezerami; nová překážka mimo zapečený navmesh rozpoznána za 1,6 s), AI-03 (7/7:
dávky ≤ maximum pásma, 0 ran při přebíjení, 5°/tik, otočka 180° ≥ 0,58 s, zásahovost 0,41 / 0,29 / 0,10 / 0,08 v 10 / 20 /
35 / 50 m), AI-04 (11/11), GAME-01/02 (11/11 + kamera po 3 smrtích v prohlížeči 3/3).

### Výkon (orientačně)

`ai.update` pro 17 botů **včetně** jejich `applyCommand` (fyzika kapsle, zbraně, hitscan): průměr 1,0 ms (čas stěny) /
1,2 ms (čas CPU) na tik, medián 0,9 ms, 99. percentil 6,8 ms (Node 22, Xeon 2,1 GHz, 120 s zápasu, `process.cpuUsage`);
celá simulace zápasu 1,38 ms CPU na tik. V Chromiu (SwiftShader, bez vykreslování) průměr 0,6–1,1 ms. Vnímání jednoho
bota: medián 0,13 ms. Stroj je sdílený (Blender a další úlohy, load average 6–20 na 4 jádrech), proto maxima jednotlivých
tiků v čase stěny (desítky až stovky ms) odpovídají přeplánování procesu, ne kódu (GC pauzy ≤ 10 ms). Největší položky
profilu: `Combatant.updateHitShapes` (klíč mezipaměti jako řetězec, volá se u každého paprsku viditelnosti i výstřelu)
a GC — navržen samostatný úkol pro herní integraci. Výkon ve skutečném prohlížeči s GPU **NOT TESTED**.

## 12. Testy

```bash
cd IronValley/Web
npm run bake:nav                      # (build to dělá sám)
node --test tests/unit/ai_*.test.mjs  # AI v Node: nav, kryty, AI-01..04 (~1–2 min)
npm run build && node --test tests/e2e/05_ai.test.mjs   # AI v sestavené hře (headless Chromium)
node tests/unit/support/aiSim.mjs --seconds 120 --seed 3  # ruční simulace zápasu 17 botů s výpisem
```

| Soubor | Obsah |
| --- | --- |
| `tests/unit/ai_units.test.mjs` | paměť (jen podněty, útlum, zapomenutí), model detekce, model míření a šumu, kontrola konfigurace, funnel |
| `tests/unit/ai_nav.test.mjs` | aktuálnost bake, parametry agenta, formát zóny, hlavní skupina, všechny trasy na navmeshi a ≤ reference, blokace + expirace, body krytu (výška paprsky, normály, dosažitelnost, rozestupy), výlučná rezervace |
| `tests/unit/ai_perception.test.mjs` | AI-01 a–d |
| `tests/unit/ai_movement.test.mjs` | AI-02: 17 botů, zablokovaná cesta |
| `tests/unit/ai_combat.test.mjs` | AI-03: reakce, zásahovost vs. model, citlivost na data, dávky, přebíjení, otáčení, pravidlo ústí |
| `tests/unit/ai_team.test.mjs` | AI-04: zápas 180 s s nečinným hráčem, 120 s bez hráče, přepočet po smrti / respawnu / novém kole |
| `tests/e2e/05_ai.test.mjs` | totéž v sestavené hře: AI živá (ne stub), AI-01, AI-02, AI-03, AI-04, 2 snímky s překryvem |
| `tests/unit/support/aiSim.mjs` | pomocník testů (MatchSession na aréně, umístění, skriptovaný hráč) — jen v `tests/` |

## 13. Známá omezení a nehotové body

- **Vyváženost arény**: tým Alfa (jih) má delší cestu přes úzká místa (dveře domu, ulička) a v krátkých zápasech boduje
  méně; do oblasti se ale dostává a bojuje (tabulka AI-04). Aréna je testovací mapa, ne herní. Kandidáti oblasti Dům a Dvůr
  (jádro je vybírá semenem i ve hře) jsou nevyvážení: Dům je ~10 m od spawnu Alfy (Alfa vyhrává; útočníci stojí u jejího
  spawnu a Alfa pak čeká na bezpečný respawn až 12–38 s — predikát spawnu funguje, jak má), Dvůr je za jedinou 2m mezerou
  K2, 57 m od Alfy a ~30 m od ostatních (oblast prázdná ~70 % kola). Rovné podmínky dává jen Střed (testy ho vynucují).
- Nejdelší zbývající epizody zaseknutí (3–4,7 s, pod limitem 5 s) jsou zácpy spoluhráčů v severních dveřích domu
  (hrana zárubně + tělo vedle).
- **Dveře**: jen průchody bez křídel (dveřní křídla zatím nejsou). Střelba oknem funguje (kryty „okno“ jen 2 body).
- Boti používají jen pušku (pistoli nevytahují), nehází granáty, neskáčou; úzké průchody jen pro dřep navmesh nezná
  (v aréně žádné nejsou).
- Sluch pro evidenci zná id zdroje zvuku (aby záznam patřil ke správnému nepříteli), polohu ale jen přibližnou.
- Navmeshe jsou v balíku `game.js` (~150 kB na úroveň). Pro mapu 350 × 350 m zvážit asynchronní načítání.
- Animace botů (třetí osoba) patří herní integraci — zatím provizorní figuríny.
- Výkon na skutečném hardwaru a chování v rámci Artifact na claude.ai: NOT TESTED.
