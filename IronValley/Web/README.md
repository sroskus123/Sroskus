# IRON VALLEY — prohlížečová verze (Web)

Hratelná prohlížečová verze hry IRON VALLEY: čistý JavaScript (three.js, WebGL2), **bez WebAssembly
a bez `eval` / `new Function` za běhu**. Obsahuje celý herní cyklus: úvodní obrazovka → výběr výbavy → kolo
tří týmů po šesti (hráč + 5 spojenců, 12 nepřátelských botů) o jednu aktivní kontrolní oblast (10 minut nebo
100 bodů) → smrt a respawn → výsledek → nové kolo. Mapy: **Zkušební prostor** (vývojová graybox mapa s krytými
spawny týmů), **AI aréna** (testovací mapa AI) a **Kalné Hamry — pracovní verze (provizorní grafika)**: skutečná mapa
350 × 350 m generovaná z návrhových dat (viz oddíl „Mapa Kalné Hamry“).

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
| `three-pathfinding` | 1.3.0 | formát zapečeného navmeshe botů (zóna), načtení za běhu; hledání cesty viz `Docs/AI.md` |
| `esbuild` (dev) | 0.28.2 | sestavení do jednoho souboru `dist/game.js` |
| `recast-navigation` (dev) | 0.43.1 | pečení navmeshe při buildu (`tools/bake_navmesh.mjs`, WebAssembly jen v Node, ne ve hře) |

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
zeď 1,0 m není schod a samotný skok ji nepřekoná (přelézt jde jen přeskokem, viz níže); svah 50° neprojde, 30° ano; práh 3 cm; dveře 0,90 m; tunel
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
po „Pokračovat“ je potřeba nový stisk, který vystřelí hned (interval mezi ranami doběhne už při otevření menu; GUN-03); HUD munice = stav jádra po částečném a prázdném přebití
i přerušení výměnou zbraně a sprintem (GUN-01); hráč třikrát zemře (vynuceně, zastřelen botem, uprostřed přebíjení)
a pokaždé se vrátí s plným zdravím, municí, ovládáním, kamerou i zbraní, spoušť držená přes smrt nevystřelí
(GAME-02, GUN-03); friendly fire vypnutý, zásahové zóny (hlava / trup / paže / nohy), ukazatel zásahu, směr
poškození, kill feed; bezpečný spawn se skriptovaně rozmístěnými nepřáteli (vzdálenost, výhled, geometrie,
těla — hráč raději čeká); celé kolo do výsledkové obrazovky a „Nové kolo“ bez načtení stránky (skóre, časy,
respawny, AI, díry po zásazích); běh AI se 17 a se 3 boty; **celé kolo se 17 boty** (`tests/e2e/09_full_round.test.mjs`:
vykreslování vypnuté, časově zrychlené přes skutečnou smyčku, kolo skončí vítězem nebo remízou, každý tým bodoval nebo
bojoval o spornou oblast, žádný bot zaseknutý 5 s, žádný teleport, žádná chyba v konzoli, „Nové kolo“ vynuluje skóre, časy,
paměť AI, rezervace krytů a blokace navmeshe); čitelnost HUD v 960×540 i 1920×1080 (bez přetečení
textu, bez překryvů); načítání map podle id; náhradní cesta pro GLB pistole.

**Optiky (`tests/e2e/10_optics.test.mjs`, `tests/unit/optics.test.mjs`, `optic_loadout.test.mjs`, `adaptive_resolution.test.mjs`):**
načtení všech optik (LOD0, LOD1, SDF, překryv); vestavěná optika skrytá; sklopná mířidla sklopená −90° (špička k pažbě,
ne dopředu do optiky) s optikou a vyklopená jen s mechanickými mířidly; pro každou optiku v plném ADS po dávce (recoil)
střed vykreslené síťky = směr zásahu (osa optiky / osa kamery PiP / střed překryvu do 0,05 px nebo 1e-4°, červené
pixely síťky do 0,75 px od bodu zásahu) + snímek `optic_ads_<ID>.png`; síťka neplave při chůzi a rozhlížení (< 0,5 px);
snímky kolem výstřelu bez NaN, bez černého snímku, síťka vždy vidět a na místě, bez záblesku a bez zablikání krytu optiky
(prominence jasu < 3); citlivost podle zvětšení; cíl obrazu v obraze nikdy menší než disk okuláru; výbava (české názvy,
náhradní ≠ hlavní) a HUD; zbrojní bedna (jen vlastní tým, v dosahu, změna ihned, `armory_menu.png`); výměna z batohu
(přesně 3 s, bez výstřelu a míření, průběh v HUD, přerušení, události fází); boti s optikou podle role jako LOD1. Unit:
data optik, pozice oka a osy v ADS (oko v kameře do 1e-9 m, osa = osa kamery), ústí podle optiky, pokrytí dilatace SDF
při 540p / 1080p, eyebox, pravidla výbavy, časování a přerušení výměny, zbraň během výměny nestřílí / nemíří / nepřebíjí,
respawn vrací výbavu, bedna jen pro svůj tým, adaptivní rozlišení se na 60 Hz vrací a v míření stojí.
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
| Použít / zbrojní bedna (u bedny svého týmu na spawnu: změna optiky) | E |
| Výměna optiky z batohu (3 s, přeruší ji znovu B, sprint nebo výměna zbraně) | B |
| Puška / pistole | 1 / 2 (pistole IV-P9 je zatím provizorní model) |
| Menu, pauza, uvolnění kurzoru | Esc (v podnabídce Esc = zpět; do hry tlačítkem „Pokračovat“) |
| FPS | F3 |

Nastavení v menu: citlivost myši, citlivost v míření (násobek) a „citlivost podle zvětšení“ (výchozí zapnuto: v míření se
rozhlížíš úhlovou rychlostí zobrazeného obrazu — 1× beze změny, 2× polovinou, 3× třetinou, 6× podle zorného pole
puškohledu), zorné pole 70–100° (horizontální, výchozí 80°), intenzita pohybu
kamery, hlasitost, automatické rozlišení nebo pevné měřítko vykreslování 50–100 %, zobrazení FPS a **změna
kláves** (klikni na akci a stiskni klávesu nebo tlačítko myši; Esc změnit nelze). Nastavení i klávesy se ukládají
do `localStorage` (když prohlížeč úložiště nepovolí, platí jen do zavření stránky).

## Herní cyklus a pravidla

* **Úvod:** Začít, Trénink (bez botů), Nastavení, Ovládání, Ukončit (webová stránka kartu sama zavřít nemůže —
  uvolní kurzor a řekne, jak hru ukončit). Volba mapy nahoře.
* **Výbava:** hlavní zbraň IV-7 karabina s optikou — Holografický zaměřovač 1×, Kolimátor 1×, Hranolový 2×, Puškohled 3×,
  Puškohled 6× nebo Mechanická mířidla — a jedna náhradní optika v batohu (nebo žádná); vedlejší IV-P9 pistole (klávesa 2).
  Optiku změníš u **zbrojní bedny** na spawnu svého týmu (E) nebo v poli výměnou s náhradní z batohu (B, 3 s, mezitím
  nestřílíš ani nemíříš; zapíše se až na konci). Po smrti se vracíš s výbavou z nabídky / bedny. Boti mají optiku podle
  role (střelec, útočník, podpora, průzkumník, určený střelec s 6×). Pravidla: `src/data/attachments.json`.
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
  nebude `public/assets/weapons/IVP9_Pistol.glb` (hra ho pak načte a z jeho socketů odvodí míření i ústí). Zvuky jsou
  skutečné nahrávky s ověřenou licencí CC0 / CC BY (výstřely AR-15 5,56 mm a Walther PPQ 9 mm z The Free Firearm
  Sound Library, mechanika zbraní, kroky po 6 površích, zásahy); vítr, průlet střely, nábojnice a část vrstev zásahů
  jsou **procedurální syntéza — prozatímní** (seznam a licence `../Shared/audio/SOURCES.md`). Smrt bota = stabilní
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
| Zvuk | `src/audio/audioSystem.js`, `src/data/audio.json`, `src/data/audio_bank.json` (generuje `../Tools/audio/build_audio.py`), `public/assets/audio/*.mp3` | WebAudio, jen události na sběrnici (výstřel blízko / daleko podle vzdálenosti se zpožděním šíření a dozvukem, přebíjení v okamžicích jádra, cvaknutí naprázdno, výměna zbraně, kroky podle povrchu, dopad, zásahy podle povrchu, průlet střely, nábojnice); HRTF panner s útlumem 1/r, dolní propust bez přímé viditelnosti (omezený počet paprsků za tik), limity hlasů na kategorii a vlastníka, náhodná výška / hlasitost, master: hlasitost (výchozí 70 %) → kompresor → limiter → měkký ořez; vítr a vzdálení ptáci jen při hraní; pauza, menu, smrt a nové kolo zastaví vše. AudioContext vzniká při kliknutí v menu. Počitadla: `window.__IV.getAudio()` |
| Klávesy | `src/player/bindingsStore.js` | přemapování kláves z dat, uložení v `localStorage` |
| HUD / menu | `src/game/hud.js`, `menus.js`, `src/styles.css` | české texty, jen skutečné hodnoty; úvod, výbava, pauza, nastavení, ovládání, výsledky |
| Testovací rozhraní | `src/debug/testApi.js` | `window.__IV` — jen pro testy a ladění, hra na něm nezávisí |
| Optiky | `src/weapons/optics.js`, `opticView.js`, `src/game/opticLoadout.js`, `armoryView.js`, `src/data/attachments.json`, `../Shared/config/optics.json` | pět optik IV-H1 / IV-R1 / IV-P2 / IV-S3 / IV-S6 + mechanická mířidla na liště IV-7 (vestavěná optika skrytá, sklopná mířidla sklopená −90° k pažbě); v míření oko v `socket_eye` optiky; 1× kolimovaná síťka z nekonečna podél osy (bez paralaxy, SDF + minimální velikost na obrazovce, nezoomuje); 2× / 3× obraz v obraze (druhá kamera se skutečným zorným polem do HDR MSAA cíle velikosti disku okuláru, síťka, vinětace, eyebox); 6× přes celou obrazovku (překryv + kamera 4,125°); citlivost podle zvětšení; výměna z batohu, zbrojní bedny, optiky botů (LOD1). Podrobně `../Art/Reference/OPTICS_spec.md` oddíl 11 |

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

### Pohyb: zatáčení, skok, přeskok, kamera (zpětná vazba z hraní 2026-09-26)

Podrobnosti a události v `Docs/GAMEPLAY_CONTRACTS.md` („Pohyb postavy“); stejné pro hráče i boty.

* **Zatáčení bez klouzání** (`src/physics/locomotion.js`): rychlost kolmá na směr pohybu se na zemi silně brzdí.
  Otočka o 90°: posun ve starém směru 0,11 m z běhu / 0,29 m ze sprintu (dříve 0,83 / 1,68 m), nový směr do
  0,08 / 0,13 s (dříve 0,43 / 0,57 s); zastavení ze sprintu 0,37 s; strafování ani zatáčení nezrychlí.
* **Skok:** za chůze, běhu i sprintu; stisk až 0,15 s před dopadem se provede při dopadu, po sejití z hrany jde
  skočit ještě 0,12 s; nikdy dvakrát ve vzduchu; bez místa nad hlavou ne. Přikrčení ve vzduchu hybnost nemaže,
  po dopadu v dřepu plynulé zpomalení (8 m/s², dříve zastavení 12 m/s² a ztráta rychlosti už ve vzduchu).
* **Přeskok / vylezení** (`src/physics/traversal.js`): Mezerník čelem k překážce 0,5–1,3 m (zeď 1,0 m, kryt,
  okno, plošina). Dráha se před startem ověří testem překryvu kapsle v krocích 3 cm a pak každý tik; nikdy nevede
  do geometrie (ověřeno i náhodným testem 320 přiblížení se spamem Mezerníku, šikmo a u rohů).
* **Kamera** (`src/player/cameraEffects.js`, jen vizuál): houpání podle skutečných kroků (nejníž při dopadu
  chodidla), drobný propad oka na každém schodu (~1–2 cm), propad při dopadu podle rychlosti pádu; vše násobí
  nastavení „Pohyb kamery“ (0 = vypnuto). Kamera přitom nekývne (jen posuny oka a náklon kolem osy pohledu), takže
  kříž i mířidla vždy ukazují směr zásahu. Po přeskoku se zbraň 0,25 s zvedá a do té doby nestřílí. Událost
  `footstep` za každý krok (zvuk, sluch AI).

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
`getMenu()`, `getCombatantViews()`, `getAIDebug()`, `loadLevel(id)`, `listLevels()`, `newRound()`,
`telemetryStart(opts)` / `telemetryReport()` / `telemetryStop()` (telemetrie zápasu `src/debug/matchTelemetry.js`: skóre
v čase, změny a spory oblasti, přítomnost týmů v oblasti, zabití / smrti / respawny, rány / zásahy / přebíjení, epizody
zaseknutí, největší posun za tik, cena tiku; totéž v Node `node tools/match_report.mjs`). `_game` je přímý přístup jen pro
interaktivní ladění.

## Webové varianty assetů (`npm run assets:web`)

GLB z Blenderu mají textury PNG (puška 16,6 MiB, optiky 19,3 MiB), což je pro prohlížeč i hostitele Artifact (limit
15 MiB na soubor po base64) moc. `../Tools/web_assets/build_web_assets.py` (Python 3 + Pillow + numpy + scipy, bez sítě
a bez Blenderu; `npm run assets:web`) z `../Art/Export/GLB` a `../Art/Textures/Optics` reprodukovatelně zapíše do
`public/assets/` webové varianty a `src/data/optics_web.json`:

| Výstup | Obsah | Velikost |
| --- | --- | --- |
| `weapons/IV7_Carbine.glb` | puška, textury ≤ 2048: základní barva WebP q90 (`EXT_texture_webp`), normála a ORM JPEG 4:4:4 q92; váhy kostí u8 (rigidní skin, přesné); sklo bez `KHR_materials_transmission` | 16,59 → 6,98 MiB |
| `optics/<ID>_*.glb`, `*_LOD1.glb` | optiky (tělo ≤ 1024, LOD1 ≤ 512), síťky WebP bezeztrátově v plném rozlišení | 19,30 → 8,83 MiB (LOD0 6,83 + LOD1 2,92) |
| `optics/<ID>_reticle_sdf.png` | pole vzdáleností síťky pro shader (R vše, G svítící, B leptané), rozsah volený tak, aby pokryl minimální šířku čar i při 960 × 540 | 12–37 KiB |
| `optics/IVS6_ads_overlay.webp` | překryv 6× (bezeztrátově, 4096², stejné px/mrad jako síťka) | 224 KiB |
| `web_assets_manifest.json` | zdroje (velikost + SHA-256) a výstupy; `tools/build.mjs` varuje, když se zdroje změnily | |

Proč JPEG 4:4:4 pro normálu a ORM: WebP ztrátově vždy podvzorkuje barvu 4:2:0; na zabaleném ORM (AO / drsnost / kov)
to míchá kanály (PSNR 25–30 dB), JPEG 4:4:4 q92 drží 39–44 dB (normála: střední úhlová chyba 0,56° / 0,88°).
Textury se dekódují z bajtů (`createImageBitmap(Blob)`), takže WebP i JPEG projdou i přísným CSP. V `dist-artifact/`
jsou kromě GLB i obrázky pod `assets/` jako `<soubor>.b64.txt`.

## Mapa Kalné Hamry (generovaná, provizorní grafika)

Mapa vzniká **jen generátorem** z návrhových dat `../Shared/level/layout.json` + `buildings.json` (rozhodnutí D10, D12);
výstupy se ručně neupravují:

```bash
python3 ../Tools/level/export_web_level.py      # ~2 min: GLB + src/data/kalne_hamry.json (s bpy: zapečené světlo)
npm run build                                  # peče navmesh (public/assets/nav/kalne_hamry.json) + balík
node tools/match_report.mjs --level kalne_hamry --bots 5,6,6 --full --zone zone_dilna   # kolo 17 botů v Node
```

| Soubor | Obsah | Velikost (base64) |
| --- | --- | --- |
| `public/assets/levels/kalne_hamry/kh_terrain.glb` | terén 0,5 m (vykreslení i kolize, 25 dlaždic 64 m), albedo 2048² (0,16 m/texel) z oblastí povrchů, roughness mapa (mokrý asfalt), rastr povrchů 0,5 m pro kroky a zásahy, okolní terén 2 m a prstenec vzdálených kopců | 8,9 MiB (11,9) |
| `public/assets/levels/kalne_hamry/kh_world.glb` | budovy (zdi s tloušťkou a skladebnými kvádry, otvory, ostění, parapety, rámy, sklo, dveřní křídla v klidové poloze, podlahy, stropy, schody, zábradlí, střechy s přesahy, žlaby, svody, komíny, sokly), vedlejší budovy jako zavřené objemy, rekvizity jako bloky správné velikosti, ploty (pletivo průhledné), zdi, opěrné zdi, mosty, potok, sloupy vedení, hraniční bariéry s cedulemi, 1650 stromů (instancované: kmen, koruna listnáče, kužel smrku) | 5,4 MiB (7,3) |
| `public/assets/levels/kalne_hamry/kh_collision.glb` | kolize ve třídách `main` (vše), `move` (jen kapsle: sklo, pletivo, zábradlí, tvrdá hranice), `movevis` (kapsle + výhled: živé ploty, keře, měkký nábytek, dřevěné bedny) | 0,4 MiB (0,5) |
| `src/data/kalne_hamry.json` | spawny 3 × 16 (řady podle zóny + záložní řady), 3 polygonové zóny s pásmem výšky, 6 zbrojních beden (u každé řady), hranice (varování, odpočet 10 s, „Minové pole“), 900 návrhových krycích bodů, 183 testovacích bodů (markery `QA_*`), přepis mlhy D9 | 0,4 MiB |
| `public/assets/nav/kalne_hamry.json` | navmesh (Recast cs 0,05 / r 0,35 m, dlaždice 12,8 m svařené na hranách), kryty z geometrie + návrhové, dosažitelnost spawn → zóna pro všechny týmy a zóny; načítá se za běhu, ne z balíku | 6,6 MB |

Světlo: slunce + obloha + mraky z `environment.json`, měkké stíny kolem hráče (rozsah 40 m), mlha D9 a **viditelnost oblohy
+ jeden odraz slunce zapečené na vrcholy při generování** (interiéry tmavší než venku), takže se při načtení nic nepeče.
Načtení mapy v Chromiu ~1,0–1,2 s (místní server: stažení 0,2 s, BVH kolize 0,5 s, GLTF 0,2 s).

Testy: `tests/unit/kalne_hamry.test.mjs` (data, čerstvost výstupů vůči zdrojům, kolizní třídy, povrchy, spawny, bedny,
zóny, hranice, navmesh, 60 s 17 botů v Node) a `tests/e2e/11_kalne_hamry.test.mjs` (načtení bez chyb, bezpečný spawn,
průchod do dílny, skladu a domu dveřmi a po schodech, celé kolo se 17 boty).

## Zbraň IV-7

Pokud existuje `public/assets/weapons/IV7_Carbine.glb`, hra ho použije jako zbraň v rukou; jinak
zobrazí zřetelně označený provizorní model (oranžové prvky, text v HUD). Aktuální GLB je webová varianta
`../Art/Export/GLB/IV7_Carbine.glb` (viz výše; Blender 4.5, konvence: ústí +X, nahoru +Y v glTF, metry, počátek na
úchopu). Pozice se řídí sockety `socket_muzzle` (ústí) a `socket_ads` (oko při míření); logické ústí pro
střelbu v `weapons.json` odpovídá skutečně vykreslené póze včetně náklonu u boku
(`viewModel.hipRotation`) — test měří polohu uzlu `socket_muzzle` v prostoru kamery po
`viewModel.update()` (do 2 mm). Vestavěná optika pušky (uzly `^Optic`) se vždy skryje a na lištu se nasadí zvolená
optika (IV-R1 je její samostatná dvojče na stejném místě). Textury vložené v GLB se dekódují přímo z bajtů (`createImageBitmap(Blob)`), bez
`blob:` URL, takže je nezablokuje ani přísné CSP hostitele (`connect-src 'self'`).

### Recoil a pocit ze střelby (`weapons.json` → `recoil`, `feel`)

- **Herní recoil** (`recoil`): kop pohledu i směru zásahu zároveň (kříž / mířidla nelžou, GUN-03), náhodný
  vodorovný kop s driftem, první rána vs. další rány série, stoupání při dávce, částečný automatický návrat
  (`recoverFraction`, zbytek zůstane v pohledu hráče), násobky pro ADS a dřep. Stejná data používají boti.
- **Vizuální vrstva** (`feel`): náklon kamery kolem osy pohledu, kop zbraně dozadu / nahoru / náklon na pružinách
  (v ADS bez rotace, aby mířidla ukazovala, kam jde rána), záblesk s pevnou dobou života (~2 snímky při 60 FPS,
  aspoň 1 snímek vždy), kouř, nábojnice ze `socket_eject` (poolované, po dopadu zmizí, událost
  `weapon:casing_landed`), zásahy podle povrchu. Vše běží na pevném ticku, výsledek je stejný při 30 / 60 / 144 FPS.
- Naměřeno (puška, 60 FPS): kop kamery 1 rány ~0,6° (ADS ~0,45°, dřep ~0,48°), zbraň 2,6 cm dozadu a 3,2° nahoru,
  dávka 10 ran ~4,8° (ADS ~3,5°), zbytek po návratu ~0,9°; pistole ~1,0° a 6,5°. Proč ho hráč v náhledu (commit
  `eec7150`) neviděl: zbraň se po ráně posunula o 0,6 mm a naklonila o 0,17° (hodnoty pružin se násobily 0,035 / 0,05)
  a kamera dostala 0,55° na ránu s návratem 7/s, takže dávka vystoupala jen na ~1,2° a za ~0,3 s zmizela. Testy
  `tests/unit/weapon_feel.test.mjs`, `tests/e2e/06_weapon_feel.test.mjs`.

## Známá omezení

* Optiky: síťky BDC / holdover jsou dekorativní, dokud hra nemá balistiku (hitscan, D8). Na 960 × 540 je šipka IV-P2
  (6 MOA při 2×) jen ~2 px — skutečná úhlová velikost; minimální šířka čar (1,25 px) ji drží viditelnou. Obraz v obraze
  vykresluje scénu podruhé (jen s úzkým zorným polem); výkon na skutečném GPU NOT TESTED. Animace rukou při výměně
  optiky zatím není (zbraň se spustí mimo obraz; události fází jsou připravené).
* Postavy, pistole a zvuky jsou **provizorní** (viz výše). FPS paže/ruce a animace přebíjení zatím nejsou (přebití
  je časovaný stav jádra s jednoduchým pohybem zbraně). Figuríny nemají animaci chůze; mezi sebou se tělesně
  nesrážejí (kapsle koliduje jen se statickou geometrií — vyhýbání řeší AI).
* Fyzikální ragdoll zatím není: po smrti se přehraje stabilní procedurální pád směrem, kde je volno (bez fyziky,
  nemůže „vybuchnout“).
* Zvuk je ověřený objektivně (unit testy s falešným AudioContextem, e2e `08_audio` v Chromiu: odemčení kliknutím,
  dekódování všech 98 souborů, správné buffery pro střelbu / přebíjení / kroky, ticho v pauze a po smrti; úrovně mixu
  `node tools/audio_mixcheck.mjs`). Poslech, prostorový dojem (HRTF) a výkon HRTF na slabém hardwaru: NOT TESTED.
* Výkon na skutečném hardwaru **nebyl změřen** (NOT TESTED). Samotná simulace 17 botů v headless Chromiu stojí
  zhruba 55–110 ms na simulovanou sekundu, tj. 0,9–1,8 ms na tik (bez vykreslování, měřeno 2026-09-27); vykreslování v SwiftShaderu (softwarově) trvá
  řádově sekundy na snímek — to není vlastnost hry.
* V režimu Artifact na claude.ai zatím **neověřeno**: zámek kurzoru (je náhrada tažením). Přísné CSP bez `blob:`
  je ověřené jen na místní simulaci hostitele (e2e test).
* „Ukončit“ kartu nezavírá (prohlížeč to webové stránce spolehlivě nedovolí); uvolní kurzor a napíše, jak hru
  ukončit.
* Nad nízkou hranou (schod, stupeň do 0,40 m) se kapsle smí opřít až 0,32 m od osy; nad vyšším srázem jen 0,15 m.
* Zapečené nepřímé světlo počítá jen jeden odraz slunce; u Zkušebního prostoru a AI arény běží při každém načtení mapy
  (~0,7 s), Kalné Hamry mají světlo zapečené při generování (`Tools/level/export_web_level.py`).
