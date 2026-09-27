# IRON VALLEY — prohlížečová verze (Web)

Hratelný základ hry IRON VALLEY pro prohlížeč: čistý JavaScript (three.js, WebGL2), **bez WebAssembly
a bez `eval` / `new Function` za běhu**. Zatím obsahuje jen vývojovou mapu **Zkušební prostor**
(graybox pro ověřování pohybu, kolizí a střelby).

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
npm run test:unit    # node --test "tests/unit/**/*.test.mjs"  (fyzika, zbraň, D8, smyčka, vstup, jádro pravidel)
npm run test:e2e     # node --test "tests/e2e/**/*.test.mjs"   (skutečný build z dist/ v headless Chromiu)
npm test             # build + unit + e2e
```

E2E testy načítají Playwright z globální instalace (`require('playwright')`, pak globální prefix npm,
nebo cesta v proměnné `PLAYWRIGHT_MODULE`). **Nestahují prohlížeče** — použije se Chromium podle
`PLAYWRIGHT_BROWSERS_PATH` (v tomto prostředí `/opt/pw-browsers`). Chromium běží s WebGL2 přes
SwiftShader (`--use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`), tj.
**softwarově**. Snímková frekvence v testech proto **není** měřítkem skutečného výkonu.

Testy ukládají snímky obrazovky do `tests/e2e/screens/` (pohled z první osoby, schody, tunel, zásah,
blokované ústí u rohu, zbraň z boku a v míření, pauza, úzký displej).

Co e2e testy ověřují (vše na sestaveném `dist/`): načtení bez chyb v konzoli a bez neúspěšných
požadavků; neprázdný a nejednolitý obraz (statistika pixelů ze snímku); shodu směru slunce oblohy a
světla; rychlosti chůze/běhu/sprintu do 5 % od konfigurace; diagonála není rychlejší; schody 0,18 m;
zeď 1,0 m nelze překonat ani skokem; svah 50° neprojde, 30° ano; práh 3 cm; dveře 0,90 m; tunel
1,40 m jen v dřepu a vstávání až venku; pád z 1,0 m s detekcí dopadu a návratem ovládání; sprint do
tenké zdi bez průniku; zásah blokovaný u ústí (roh i nízký kryt); stejný počet výstřelů za 3 s při
30/60/144 FPS; zákmit zbraně po výstřelu omezený a stejný při 4–144 FPS; obraz za menu pauzy stojí;
Esc a ztráta fokusu uvolní vstup a zastaví palbu; náhradní rozhlížení tažením myši, když prohlížeč
zámek kurzoru odmítne; načtení a orientaci modelu IV-7 (GLB), logické ústí = vykreslený socket
(do 2 mm); spuštění pod přísným CSP hostitele (bez `blob:`) i s texturami zbraně; detail mraků při
pohledu vzhůru; kontrast malých popisků HUD (≥ 4,5 : 1 i na bílém pozadí).

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
| Puška / pistole | 1 / 2 (pistole zatím není) |
| Menu, pauza, uvolnění kurzoru | Esc |
| FPS | F3 |

Nastavení v menu: citlivost myši, zorné pole 70–100° (horizontální, výchozí 80°), intenzita pohybu
kamery, automatické rozlišení nebo pevné měřítko vykreslování 50–100 %, zobrazení FPS.

## Technický přehled

| Oblast | Soubor(y) | Stručně |
| --- | --- | --- |
| Smyčka | `src/engine/loop.js` | pevný krok 1/60 s, akumulátor z absolutního času (stejný počet kroků při libovolném FPS), interpolace vykreslení, ořez velkých mezer 0,25 s |
| Vykreslování | `src/engine/renderer.js`, `environment.js`, `clouds.js`, `heightFog.js` | WebGL2, sRGB, ACES filmic, PBR, jedno slunce s měkkými stíny sledujícími hráče (přichycení na texely), obloha `Sky.js` se *stejným* vektorem slunce jako světlo, vlastní vrstva mraků (zakřivená vrstva, víceoktávový šum s LOD podle derivací, osvětlení pochodem ke slunci), PMREM prostředí z oblohy, vzdálenostní + výšková mlha, adaptivní rozlišení |
| Události | `src/engine/events.js` | jednoduchá sběrnice událostí |
| Vstup | `src/player/input.js`, `settings.js`, `player.js` | vazby z JSON, zámek kurzoru s náhradou, Esc/blur uvolní vše, krátké stisky se neztratí |
| Kolize | `src/physics/collisionWorld.js` | statický svět z geometrie úrovně, BVH (three-mesh-bvh) |
| Postava | `src/physics/characterController.js`, `sweep.js` | kinematická kapsle (r 0,35 m, 1,80/1,20 m, oči 1,65/1,05 m), sdílená hráčem i boty; parametry v `src/data/movement.json` |
| Tuhá tělesa | `src/physics/dynamicsWorld.js` | cannon-es, statické kvádry úrovně, krok na stejném pevném ticku |
| Úroveň | `src/level/*`, `src/data/test_range.json` | datově popsaný Zkušební prostor |
| Střelba | `src/weapons/*`, `src/data/weapons.json` | hitscan podle D8 (kamera určí bod, zásah rozhoduje paprsek od ústí), kadence z akumulovaného simulačního času, recoil s návratem, díry po zásazích, jiskry, záblesk a světlo u ústí; pružiny zákmitu zbraně (`viewModelMotion.js`) běží na pevném ticku s přesným řešením tlumené pružiny a vykreslení je interpoluje, houpání zbraně závisí na úhlové rychlosti pohledu, ne na FPS |
| Terče | `src/game/targetDummies.js`, `dummyView.js` | analytické zásahové zóny (hlava, trup, nohy) shodné s modelem |
| HUD / menu | `src/game/hud.js`, `src/styles.css` | české texty, skutečný stav munice |
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
* Přichycení k zemi při chůzi dolů (analytický sweep koule až 0,40 m), jinak pád; letmý dotyk hrany
  dalšího stupně (úzké schody) sondu neblokuje; detekce dopadu.
* Vstát z dřepu lze jen při volném prostoru; skok ~0,45 m s kontrolou kolize.

### Testovací rozhraní `window.__IV`

`getState()`, `pause()` / `resume()` / `step(n)` / `frames(dt, count)`, `setTimeScale(s)`,
`keyDown/keyUp/mouseMove/mouseButton`, `teleport(...)`, `teleportToMarker(name)`, `setLook(yaw, pitch)`,
`lookAt(x, y, z)`, `setRenderOnStep(bool)`, `renderNow()`, `startGame()`, `openMenu()`,
`setInfiniteAmmo(bool)`, `refillAmmo()`, `setSetting(k, v)`, `muzzleConsistency()`, `setLighting({...})`
(ladění), `setDrawEnabled(bool)` (celá aktualizace snímku bez volání WebGL — pro rychlé testy v
SwiftShaderu). `_game` je přímý přístup jen pro interaktivní ladění.

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

* Jen Zkušební prostor, žádná herní mapa, boti, zvuk, FPS paže/ruce, pistole ani animace přebíjení
  (přebití je zatím jen časovaný stav s jednoduchým pohybem zbraně).
* Výkon na skutečném hardwaru **nebyl změřen** (NOT TESTED). V SwiftShaderu se snímek s modelem pušky
  kreslí řádově přes sekundu — to je softwarové vykreslování, ne vlastnost hry.
* V režimu Artifact na claude.ai zatím **neověřeno**: zámek kurzoru (je náhrada tažením). Přísné CSP
  bez `blob:` je ověřené jen na místní simulaci hostitele (e2e test), ne na skutečném claude.ai.
* Stav munice je zatím v `src/weapons/weaponState.js`; autoritativní pravidla munice vznikají v
  `src/core` (sdílená s C++) a mají ho nahradit.
* Nad nízkou hranou (schod, stupeň do 0,40 m) se kapsle smí opřít až 0,32 m od osy; nad vyšším srázem
  jen 0,15 m. Pro boty bude potřeba chodidla umisťovat podle skutečného bodu opory (IK).
