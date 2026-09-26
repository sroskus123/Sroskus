# IRON VALLEY — prohlížečová verze (Web)

Hratelná prohlížečová verze hry IRON VALLEY: čistý JavaScript (three.js, WebGL2), **bez WebAssembly
a bez `eval` / `new Function` za běhu**. Obsahuje celý herní cyklus: úvodní obrazovka → výběr výbavy → kolo
tří týmů po šesti (hráč + 5 spojenců, 12 nepřátelských botů) o jednu aktivní kontrolní oblast (10 minut nebo
100 bodů) → smrt a respawn → výsledek → nové kolo. Mapy: **Zkušební prostor** (vývojová graybox mapa s krytými
spawny týmů) a **AI aréna** (připravuje modul AI); Kalné Hamry přibudou později.

> **Toto není verze v Unreal Engine.** Projekt UE5 se připravuje zvlášť (adresář `../Unreal`) a v tomto
> prostředí nebyl spuštěn ani zkompilován. Vše níže se týká jen webové verze.

## Požadavky

| Co | Verze | Poznámka |
| --- | --- | --- |
| Node.js | 22 a novější (ověřeno 22.22.2) | `node --test` s glob vzory potřebuje Node 22 |
| npm | 10 (ověřeno 10.9.7) | |
| Prohlížeč | aktuální Chrome / Edge / Firefox s WebGL2 | hra vyžaduje klávesnici a myš |
| Playwright | 1.56.1 (jen pro `test:e2e`) | **není** v závislostech projektu, používá se globální instalace |

### Přesné verze závislostí (package.json, `--save-exact`)

| Balíček | Verze | Použití |
| --- | --- | --- |
| `three` | 0.186.1 | vykreslování, obloha (`Sky.js`), načítání GLB (`GLTFLoader`) |
| `three-mesh-bvh` | 0.9.15 | BVH statického kolizního světa, raycasty, kapslový kontroler |
| `cannon-es` | 0.20.0 | svět tuhých těles (zatím kostra pro ragdoll, dveře, předměty) |
| `three-pathfinding` | 1.3.0 | připraveno pro navigaci botů (zatím se za běhu nepoužívá) |
| `esbuild` (dev) | 0.28.2 | sestavení do jednoho souboru `dist/game.js` |

## Instalace, sestavení, spuštění

```bash
cd IronValley/Web
npm install          # nebo: npm ci (přesně podle package-lock.json)
npm run build        # -> dist/
npm run serve        # vypíše adresu, např. http://127.0.0.1:43127/
```

`npm run serve` spustí malý statický server bez závislostí (`tools/serve.mjs`) na volném místním portu
(poslouchá jen na `127.0.0.1`). Pevný port: `node tools/serve.mjs --port 8080`. Adresa platí jen pro
počítač, na kterém server běží.

Výstup sestavení (`dist/`):

| Soubor | Účel |
| --- | --- |
| `index.html` | kompletní stránka pro místní spuštění |
| `artifact.html` | stejný obsah **bez** `<!doctype>`, `<html>`, `<head>`, `<body>` — začíná `<title>Iron Valley</title>` a blokem `<style>`; pro hostitele, který stránku obalí vlastní kostrou (claude.ai Artifact) |
| `game.js` | celá hra v jednom IIFE souboru |
| `assets/…` | kopie `public/` (např. `assets/weapons/IV7_Carbine.glb`) |
| `build-info.json` | verze, velikost balíku, seznam assetů |

Sestavení samo kontroluje, že `game.js` neobsahuje `eval(`, `new Function(` ani `WebAssembly`
(jinak skončí chybou). Seznam existujících assetů se vkládá do balíku, takže hra žádá jen soubory, které
existují (žádné 404). GLB nesmí vyžadovat Draco / meshopt / KTX2 (dekodéry používají WebAssembly).

## Testy

```bash
npm run test:unit    # node --test "tests/unit/**/*.test.mjs"  (fyzika, zbraň, D8, smyčka, vstup, jádro pravidel, zápas)
npm run test:e2e     # node --test "tests/e2e/**/*.test.mjs"   (skutečný build z dist/ v headless Chromiu)
npm test             # build + unit + e2e
```

E2E testy načítají Playwright z globální instalace (`require('playwright')`, pak globální prefix npm,
nebo cesta v proměnné `PLAYWRIGHT_MODULE`). **Nestahují prohlížeče** — použije se Chromium podle
`PLAYWRIGHT_BROWSERS_PATH` (v tomto prostředí `/opt/pw-browsers`). Chromium běží s WebGL2 přes
SwiftShader (`--use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`), tj.
**softwarově**. Snímková frekvence v testech proto **není** měřítkem skutečného výkonu.

Testy ukládají snímky obrazovky do `tests/e2e/screens/` (pohled z první osoby, schody, tunel, zásah,
blokované ústí u rohu, zbraň z boku a v míření, pauza, úzký displej; nově úvodní menu `menu_title.png`, výbava
`menu_loadout.png`, nastavení `menu_settings.png` / `pause_settings.png`, pauza v zápase `pause_menu_match.png`,
HUD ve hře `hud_play.png` a `hud_1080p.png`, pistole `pistol_placeholder.png`, pohled po smrti `death_view.png`,
po respawnu `after_respawn.png`, výsledek kola `results.png`, zápas se 17 boty `bots_17.png`).

Co e2e testy ověřují (vše na sestaveném `dist/`): načtení bez chyb v konzoli a bez neúspěšných
požadavků; neprázdný a nejednolitý obraz (statistika pixelů ze snímku); shodu směru slunce oblohy a
světla; rychlosti chůze/běhu/sprintu do 5 % od konfigurace; diagonála není rychlejší; schody 0,18 m;
zeď 1,0 m nelze překonat ani skokem; svah 50° neprojde, 30° ano; práh 3 cm; dveře 0,90 m; tunel
1,40 m jen v dřepu a vstávání až venku; pád z 1,0 m s detekcí dopadu a návratem ovládání; sprint do
tenké zdi bez průniku; zásah blokovaný u ústí (roh i nízký kryt); stejný počet výstřelů za 3 s při
30/60/144 FPS; zákmit zbraně po výstřelu omezený a stejný při 4–144 FPS; obraz za menu pauzy stojí;
Esc a ztráta fokusu uvolní vstup a zastaví palbu; náhradní rozhlížení tažením myši, když prohlížeč
zámek kurzoru odmítne; načtení a orientaci modelu IV-7 (GLB), logické ústí = vykreslený socket
(do 2 mm, i během přechodu do míření); spuštění pod přísným CSP hostitele (bez `blob:`) i s texturami
zbraně; detail mraků při pohledu vzhůru; kontrast malých popisků HUD (≥ 4,5 : 1 i na bílém pozadí);
žádné přímé slunce pod střechou tunelu (pás stěny stejný se sluncem i bez něj); vnitřek tunelu dostává
výrazně méně okolního světla než stejná stěna venku; houpání kamery při 144 FPS interpolované (žádné
60Hz schody); otočka přes hranici úhlu nezaškube zbraní; zasažený terč za menu pauzy stojí.


**Herní cyklus (`tests/e2e/04_match.test.mjs`, `tests/unit/game_session.test.mjs`):** menu a nastavení (citlivost,
FOV, hlasitost, změna kláves s uložením, Esc zpět, kurzor nikdy nezůstane zamčený — UI-01); výbava (mechanická
mířidla skryjí kolimátor); HUD ukazuje skutečné hodnoty; Esc pozastaví hru se zámkem `menu` v jádru, nic nestřílí,
po „Pokračovat“ je potřeba nový stisk (GUN-03); HUD munice = stav jádra po částečném a prázdném přebití
i přerušení výměnou zbraně a sprintem (GUN-01); hráč třikrát zemře (vynuceně, zastřelen botem, uprostřed přebíjení)
a pokaždé se vrátí s plným zdravím, municí, ovládáním, kamerou i zbraní, spoušť držená přes smrt nevystřelí
(GAME-02, GUN-03); friendly fire vypnutý, zásahové zóny (hlava / trup / paže / nohy), ukazatel zásahu, směr
poškození, kill feed; bezpečný spawn se skriptovaně rozmístěnými nepřáteli (vzdálenost, výhled, geometrie,
těla — hráč raději čeká); celé kolo do výsledkové obrazovky a „Nové kolo“ bez načtení stránky (skóre, časy,
respawny, AI, díry po zásazích); běh AI se 17 a se 3 boty; čitelnost HUD v 960×540 i 1920×1080 (bez přetečení
textu, bez překryvů); načítání map podle id; náhradní cesta pro GLB pistole.
## Ovládání (výchozí, `src/data/input_bindings.json`)

| Akce | Klávesa |
| --- | --- |
| Pohyb | W A S D (i šipky) |
| Rozhlížení | myš (po kliknutí se zamkne kurzor; když to prohlížeč odmítne, rozhlížení tažením se stisknutým tlačítkem) |
| Střelba / míření | levé / pravé tlačítko myši |
| Přebití | R |
| Sprint (jen vpřed) | Shift |
| Chůze (držet) | Alt |
| Dřep | C nebo Ctrl (Ctrl+W v prohlížeči zavírá kartu — doporučujeme C) |
| Skok | mezerník |
| Použít | E |
| Puška / pistole | 1 / 2 (pistole IV-P9 je zatím provizorní model) |
| Menu, pauza, uvolnění kurzoru | Esc (v podnabídce Esc = zpět; do hry tlačítkem „Pokračovat“) |
| FPS | F3 |

Nastavení v menu: citlivost myši, zorné pole 70–100° (horizontální, výchozí 80°), intenzita pohybu
kamery, hlasitost, automatické rozlišení nebo pevné měřítko vykreslování 50–100 %, zobrazení FPS a **změna
kláves** (klikni na akci a stiskni klávesu nebo tlačítko myši; Esc změnit nelze). Nastavení i klávesy se ukládají
do `localStorage` (když prohlížeč úložiště nepovolí, platí jen do zavření stránky).

## Herní cyklus a pravidla

* **Úvod:** Začít, Trénink (bez botů), Nastavení, Ovládání, Ukončit (webová stránka kartu sama zavřít nemůže —
  uvolní kurzor a řekne, jak hru ukončit). Volba mapy nahoře.
* **Výbava:** hlavní zbraň IV-7 karabina (kolimátor / mechanická mířidla), vedlejší IV-P9 pistole (klávesa 2).
* **Kolo:** 5 s odpočet, pak 10 minut. Aktivní oblast vybere jádro ze tří míst mapy podle semene zápasu. Oblast drží
  tým s jednoznačně největším počtem živých členů uvnitř; 1 bod za 2 s; vyhrává 100 bodů nebo nejvyšší skóre
  po 10 minutách (shoda = remíza). Všechny hodnoty v `Shared/config/rules.json`.
* **Smrt a respawn:** krátký pohled po smrti (kamera klesne k zemi), odpočet 5 s, respawn na bezpečném bodě týmu
  (jádro `RespawnSystem` + predikát enginu: kapsle se vejde a pod ní je zem, žádné jiné tělo blíž než 1,5 m, žádný
  živý nepřítel blíž než 25 m (přísnější hodnota z `rules.json` a `combat.json`) a žádný ho nevidí). Když žádný bod
  bezpečný není, hráč čeká („Čekám na bezpečné místo…“). Respawn obnoví zdraví, výbavu (30+1 / 90, 15+1 / 45),
  stav přebíjení, kameru, ovládání a viditelnost.
* **Zásahy:** hitscan s ověřením od ústí (D8) — stejný kód pro hráče i boty; poškození zbraně z `rules.json`
  × násobek zóny z `src/data/combat.json` (hlava 2,0, trup 1,0, paže 0,7, nohy 0,75); zdraví a smrt autoritativně
  v jádru `Match`; friendly fire vypnutý (`rules.json`). Mrtvý nestřílí ani nepřebíjí (zámek `life` v jádru),
  v menu platí zámek `menu`, na výsledkové obrazovce `results`.
* **HUD:** zdraví, munice (zásobník + náboj v komoře + rezerva), zbraň a mířidla, režim palby, průběh přebíjení,
  aktivní oblast (název, vzdálenost, směrová šipka, stav: drží tým / sporná / prázdná, postup k dalšímu bodu),
  skóre týmů, čas kola, jmenovky spojenců (i přes zdi, jen spojenci), ukazatel zásahu, směr poškození,
  odpočet respawnu, krátký kill feed.
* **Nové kolo** z výsledkové obrazovky vše vynuluje bez načtení stránky (jádro `Match.reset`, bojovníci,
  časovače, `ai.reset()`, díry po zásazích, kill feed). „Změnit výbavu“ vede znovu přes výběr výbavy.
* **Provizorní assety (zřetelně označené v HUD):** vojáci jsou jednoduché figuríny v barvě týmu složené přesně ze
  zásahových zón (co vidíš, to zasáhneš), s uzly pojmenovanými jako kostra Unreal Mannequin (`pelvis`,
  `spine_01..03`, `head`, `hand_r` …) pro pozdější GLB; pistole je model z primitiv s oranžovými prvky, dokud
  nebude `public/assets/weapons/IVP9_Pistol.glb` (hra ho pak načte a z jeho socketů odvodí míření i ústí); zvuky jsou
  syntetizované zástupné zvuky (výstřel, cvaknutí, zásah, kroky), ne finální assety. Smrt bota = stabilní
  procedurální pád (fyzikální ragdoll přijde později, háček je událost `combatant:died`).

## Technický přehled

| Oblast | Soubor(y) | Stručně |
| --- | --- | --- |
| Smyčka | `src/engine/loop.js` | pevný krok 1/60 s, akumulátor z absolutního času (stejný počet kroků při libovolném FPS), interpolace vykreslení, ořez velkých mezer 0,25 s |
| Vykreslování | `src/engine/renderer.js`, `environment.js`, `clouds.js`, `heightFog.js` | WebGL2, sRGB, ACES filmic, PBR, jedno slunce s měkkými stíny sledujícími hráče (přichycení na texely; rozsah hloubky stínové kamery se každý snímek přizpůsobí výškám scény a posun `shadowBiasMeters` je v metrech, takže světlo neprosakuje pod střechy), obloha `Sky.js` se *stejným* vektorem slunce jako světlo, vlastní vrstva mraků (zakřivená vrstva, víceoktávový šum s LOD podle derivací, osvětlení pochodem ke slunci, vzdušná perspektiva jen pro vzduch pod vrstvou), PMREM prostředí z oblohy se sníženou sytostí a s osluněnou zemí pod horizontem (odražené světlo), vzdálenostní + výšková mlha, adaptivní rozlišení |
| Nepřímé světlo | `src/engine/indirectBake.js`, `bakedLightingMaterial.js`, `src/level/lightingGeometry.js` | při načtení se pro každý vrchol jemně dělené geometrie úrovně zapeče viditelnost oblohy (tlumí okolní světlo jako AO) a jeden odraz slunce od osluněných ploch (paprsky BVH, cca 0,7 s); dynamické objekty (zbraň v rukou, terče) mají sondu viditelnosti oblohy; adaptace oka zvýší expozici v uzavřeném prostoru (`environment.json` → `bakedLighting`, `eyeAdaptation`) |
| Události | `src/engine/events.js` | jednoduchá sběrnice událostí |
| Vstup | `src/player/input.js`, `settings.js`, `player.js` | vazby z JSON, zámek kurzoru s náhradou, Esc/blur uvolní vše, krátké stisky se neztratí |
| Kolize | `src/physics/collisionWorld.js` | statický svět z geometrie úrovně, BVH (three-mesh-bvh) |
| Postava | `src/physics/characterController.js`, `sweep.js` | kinematická kapsle (r 0,35 m, 1,80/1,20 m, oči 1,65/1,05 m), sdílená hráčem i boty; parametry v `src/data/movement.json` |
| Tuhá tělesa | `src/physics/dynamicsWorld.js` | cannon-es, statické kvádry úrovně, krok na stejném pevném ticku |
| Úroveň | `src/level/*`, `src/data/test_range.json`, `src/data/levels.json` | datově popsané mapy; blok `match` = spawny týmů a tři oblasti; tělesa s `bvhGroup` mají vlastní kolizní BVH |
| Střelba | `src/weapons/*`, `src/data/weapons.json` | hitscan podle D8 (kamera určí bod, zásah rozhoduje paprsek od ústí), kadence z akumulovaného simulačního času, recoil s návratem, díry po zásazích, jiskry, záblesk a světlo u ústí; pružiny zákmitu zbraně (`viewModelMotion.js`) běží na pevném ticku s přesným řešením tlumené pružiny a vykreslení je interpoluje, houpání zbraně závisí na úhlové rychlosti pohledu, ne na FPS |
| Terče | `src/game/targetDummies.js`, `dummyView.js` | analytické zásahové zóny (hlava, trup, nohy) shodné s modelem |
| Zápas | `src/game/session.js`, `combatant.js`, `combatants.js`, `worldQuery.js`, `hitShapes.js`, `gameRules.js`, `levels.js` | relace zápasu bez DOM (běží i v Node testech): jádro `Match`, bojovníci (hráč i boti stejný `applyCommand`), predikát spawnu, poškození, kolo, reset; úrovně podle id ze `src/data/<id>.json` |
| AI | `src/ai/**` (modul AI) | napojené přes `createAISystem` podle `Docs/GAMEPLAY_CONTRACTS.md` |
| Postavy / oblast | `src/game/characterView.js`, `combatantViews.js`, `zoneView.js` | provizorní figuríny, interpolace, pád po smrti, záblesky u ústí botů, kruh aktivní oblasti |
| Zvuk | `src/game/audio.js` | WebAudio, jen jednorázové zvuky spuštěné událostmi, prostorové, hlavní hlasitost |
| Klávesy | `src/player/bindingsStore.js` | přemapování kláves z dat, uložení v `localStorage` |
| HUD / menu | `src/game/hud.js`, `menus.js`, `src/styles.css` | české texty, jen skutečné hodnoty; úvod, výbava, pauza, nastavení, ovládání, výsledky |
| Testovací rozhraní | `src/debug/testApi.js` | `window.__IV` — jen pro testy a ladění, hra na něm nezávisí |

### Kapslový kontroler — klíčová pravidla

* Pohyb po malých podkrocích (≤ 0,1 m), proto ani sprint 5,8 m/s neprojde zdí 0,1 m.
* Pochůznost se posuzuje podle normály *plochy* (limit 45°), podobně jako CharacterMovement v Unrealu.
  Strmé plochy se řeší jen vodorovně — nedají se vyšplhat.
* Dva poloměry opory na hraně: `perchRadius` 0,32 m — hrany nízkých pochůzných ploch (nosy schodů,
  práh) kapsle při chůzi plynule „přejede“; `standPerchRadius` 0,15 m — skutečná opora: dál než 0,15 m
  za hranou kapsle stojí jen tehdy, když je pod osou pochůzná plocha nejvýš 0,40 m níž (schody, nízký
  stupeň), jinak z hrany spadne. Ve vzduchu lze dosednout jen na hranu do 0,15 m od osy (posuzováno
  v okamžiku prvního dotyku), takže skok s vrcholem 0,45 m vyleze nejvýš na ~0,48 m (ne na 0,65 m).
* Vyšší stupně řeší explicitní krok (zvednutí → posun → dosednutí) do 0,40 m, posuzovaný podle výšky
  bodu opory. Posun se prodlouží směrem ke stěně stupně, takže krok funguje v jakémkoli úhlu náběhu;
  krok se přijme jen tehdy, když kapsle opravdu vystoupala za čelo stupně (u vysoké zdi nikdy — ani
  nezrychlí klouzání podél zdi). Zeď 1,0 m proto nikdy není schod.
* Krok dolů / přichycení k zemi (analytický sweep koule až 0,40 m): nová opora smí být nejvýš
  `maxStepHeight` (0,40 m) pod bodem, na kterém kapsle stála — při jakékoli rychlosti, takže strmé
  schody (0,25–0,40 m) a nízké stupně se scházejí bez pádu, vyšší sráz je vždy pád. Hranu, ze které
  kapsle sjíždí, obkutálí spodní koulí až na nižší plochu (bez vznášení a bez bočního poskoku); letmý
  dotyk hrany dalšího stupně (úzké schody) sondu neblokuje; detekce dopadu.
* Vstát z dřepu lze jen při volném prostoru; skok ~0,45 m s kontrolou kolize.

### Testovací rozhraní `window.__IV`

Původní funkce zůstávají: `getState()`, `pause()` / `resume()` / `step(n)` / `frames(dt, count)`, `setTimeScale(s)`,
`keyDown/keyUp/mouseMove/mouseButton`, `teleport(...)`, `teleportToMarker(name)`, `setLook(yaw, pitch)`,
`lookAt(x, y, z)`, `setRenderOnStep(bool)`, `renderNow()`, `startGame()` (vstup do hry bez gesta — **volný trénink**
bez botů a bez času kola), `openMenu()`, `setInfiniteAmmo(bool)`, `refillAmmo()` (přes jádro), `setSetting(k, v)`,
`muzzleConsistency()`, `setLighting({...})`, `setEyeAdaptation(bool)`, `setDrawEnabled(bool)`.

Zápas (testy): `startMatch({ level, bots: [t0, t1, t2], seed, optic, skipPreRound, ai, rules })` (zápas bez menu;
`rules` = JSON merge patch jen pro testy), `listCombatants()` (tým, život, zdraví, poloha, stav zbraní),
`forceKill(id)` (jen test), `setBotCount([..])` (běhy se 3 a 17 boty), `setSeed(n)`, `setAIEnabled(bool)`,
`simulate(sekundy)` / `simulateUntil({...})` (rychlá simulace bez vykreslování), `getMatchState()`,
`getSpawnHistory()`, `getDeathLog()`, `evaluateSpawnPoint(x, y, z, tým)`, `placeCombatant(...)`,
`aimCombatant(...)`, `driveBot(id, cmd, ticks)` (skriptované boty, jen test), `getCoreWeapon()`, `getHud()`,
`getMenu()`, `getCombatantViews()`, `getAIDebug()`, `loadLevel(id)`, `listLevels()`, `newRound()`. `_game` je
přímý přístup jen pro interaktivní ladění.

## Zbraň IV-7

Pokud existuje `public/assets/weapons/IV7_Carbine.glb`, hra ho použije jako zbraň v rukou; jinak
zobrazí zřetelně označený provizorní model (oranžové prvky, text v HUD). Aktuální GLB je kopie
`../Art/Export/GLB/IV7_Carbine.glb` (Blender 4.5, konvence: ústí +X, nahoru +Y v glTF, metry, počátek na
úchopu). Pozice se řídí sockety `socket_muzzle` (ústí) a `socket_ads` (oko při míření); logické ústí pro
střelbu v `weapons.json` odpovídá skutečně vykreslené póze včetně náklonu u boku
(`viewModel.hipRotation`) — test měří polohu uzlu `socket_muzzle` v prostoru kamery po
`viewModel.update()` (do 2 mm). Sklo optiky používá `KHR_materials_transmission`,
které by ve zvláštním průchodu pro zbraň vykreslilo černou čočku — hra ho při načtení nahradí tenkým
průhledným sklem. Textury vložené v GLB se dekódují přímo z bajtů (`createImageBitmap(Blob)`), bez
`blob:` URL, takže je nezablokuje ani přísné CSP hostitele (`connect-src 'self'`).

## Známá omezení

* Postavy, pistole a zvuky jsou **provizorní** (viz výše). FPS paže/ruce a animace přebíjení zatím nejsou (přebití
  je časovaný stav jádra s jednoduchým pohybem zbraně). Figuríny nemají animaci chůze; mezi sebou se tělesně
  nesrážejí (kapsle koliduje jen se statickou geometrií — vyhýbání řeší AI).
* Fyzikální ragdoll zatím není: po smrti se přehraje stabilní procedurální pád směrem, kde je volno (bez fyziky,
  nemůže „vybuchnout“).
* Zvuk je ověřený jen technicky (události, hlasitost v `getState().audio`); poslech a prostorový dojem: NOT TESTED.
* Výkon na skutečném hardwaru **nebyl změřen** (NOT TESTED). Samotná simulace 17 botů v headless Chromiu stojí
  zhruba 75–95 ms na simulovanou sekundu (bez vykreslování); vykreslování v SwiftShaderu (softwarově) trvá
  řádově sekundy na snímek — to není vlastnost hry.
* V režimu Artifact na claude.ai zatím **neověřeno**: zámek kurzoru (je náhrada tažením). Přísné CSP bez `blob:`
  je ověřené jen na místní simulaci hostitele (e2e test).
* „Ukončit“ kartu nezavírá (prohlížeč to webové stránce spolehlivě nedovolí); uvolní kurzor a napíše, jak hru
  ukončit.
* Nad nízkou hranou (schod, stupeň do 0,40 m) se kapsle smí opřít až 0,32 m od osy; nad vyšším srázem jen 0,15 m.
* Zapečené nepřímé světlo počítá jen jeden odraz slunce; pečení běží při každém načtení mapy (~0,7 s pro
  Zkušební prostor); pro velkou mapu bude potřeba péct při sestavení.
