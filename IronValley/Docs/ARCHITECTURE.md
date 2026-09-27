# IRON VALLEY — architektura a rozhodnutí

Závazný kontrakt pro všechny části projektu. Změnu rozhodnutí zapiš sem do deníku rozhodnutí.

## Deník rozhodnutí

| ID | Datum | Rozhodnutí | Důvod |
| --- | --- | --- | --- |
| D1 | 2026-09-26 | **Hybridní postup** schválený uživatelem: hratelná verze pro prohlížeč (WebGL, three.js) vzniká a testuje se v tomto prostředí; paralelně se připravuje projekt Unreal Engine 5 (assety FBX, C++ zdroj, importní skripty) k dokončení na stroji s UE5. | UE5 v cloudovém kontejneru nejde provozovat (bez GPU, domény Epic blokované, málo disku). Zadání zakazuje přechod na webový engine bez souhlasu — souhlas byl dán. |
| D2 | 2026-09-26 | **Higgsfield se nepoužívá**, dokud nebude připojen. HF-01 = BLOCKED. Nenahrazuje se jinou službou. | Žádný konektor, doména blokovaná. Uživatel zvolil pokračovat bez něj. |
| D3 | 2026-09-26 | Webový runtime je **čistý JavaScript bez WebAssembly**: `three@0.186.1`, `three-mesh-bvh@0.9.15` (kolize postavy, raycasty), `cannon-es@0.20.0` (ragdoll, dveře, drobné předměty), `three-pathfinding@1.3.0` (hledání cesty po navmeshi). | Hra se předává jako soukromý Artifact v uzamčeném rámci; povolení kompilace WASM tam nelze ověřit. Čistý JS běží všude. |
| D4 | 2026-09-26 | Navmesh se **peče předem** při buildu (Node, `recast-navigation` — WASM jen v build nástroji) a do hry jde jako JSON. | Runtime zůstává bez WASM. |
| D5 | 2026-09-26 | Build `esbuild`; testy logiky `node --test`; prohlížečové testy Playwright (headless Chromium, WebGL2 přes SwiftShader). | Jednoduché, rychlé, bez další infrastruktury. |
| D6 | 2026-09-26 | Pravidla (munice, kontrolní bod, kolo, respawn) existují jako **čisté jádro** dvakrát: JS (`Web/src/core`) a C++ (`Core/`), obě implementace procházejí **stejnými testovacími vektory** (`Shared/testvectors/*.json`). | Pravidla se automaticky ověřují; UE5 modul pak použije C++ jádro. |
| D7 | 2026-09-26 | Pohyb postavy vlastní **kinematický kapslový kontroler** (hráč i boti). Lokomoční animace jsou in-place a jejich rychlost přehrávání se odvozuje od skutečné rychlosti kapsle. Root motion se v první verzi nepoužívá. | Jeden vlastník pohybu, žádné dvojí posouvání (ANIM-01). |
| D8 | 2026-09-26 | Střelba = hitscan. Kamera určuje zamýšlený bod, zásah se ověřuje paprskem **od ústí hlavně** k tomuto bodu; překážka mezi ústím a cílem zachytí zásah. Totéž platí pro boty. Palebný interval se počítá z akumulovaného času, ne z délky snímku. | GUN-02, GUN-03. |
| D9 | 2026-09-26 | Mapa **Kalné Hamry** přebírá slunce, oblohu, mraky a expozici beze změny z `Web/src/data/environment.json` (slunce 222°/38°), ale používá **vlastní mlhu**: barva `#c3cfd9`, hustota 0,0012, výšková hustota 0,0006, výškový pokles 0,08 (`layout.json` → `environment.fog.map_override_D9`). | Hodnoty mlhy v `environment.json` (0,0045 / 0,0035) jsou laděné pro 80m střelnici. Na mapě 350 m by na 150 m vzaly 59 % kontrastu a smazaly vzdálené kopce. S D9 je mlha ~10 % na 150 m (limit vnímání AI) a ~40 % na 600 m. |
| D10 | 2026-09-26 | **Datový kontrakt úrovně:** `Shared/level/layout.json` + `buildings.json` + `terrain_ref_0p5m.png` jsou závazná data mapy. Vytváří je jen `Tools/level/run_pipeline.py` (ruční úpravy JSON jsou zakázané) a platí jen tehdy, když `Tools/level/check_layout.py` hlásí 0 FAIL. Ověřovací bake navmeshe (Recast): **cs 0,05 m, radius 7 buněk (0,35 m), height 36, climb 8, sklon 45°**; hrubší bake je zakázaný. Dveře na trasách mají světlost ≥ 1,10 m. | Zkušební bake s cs 0,10 / r 4 zúžil koridor U-schodiště domu na nulu. Při cs 0,05 zůstává ve dveřích a na schodech koridor ≥ 0,40 m. Kontrola s hashem dat odhalí zastaralý bake. |
| D11 | 2026-09-27 | **Optiky ve webu:** sklo optik bez transmise / refrakce (tenké tónované sklo), 1× síťka kolimovaná z nekonečna podél osy optiky (pole vzdáleností + minimální velikost na obrazovce, nepodléhá tone mappingu), 2× / 3× obraz v obraze (druhá kamera se skutečným zorným polem, HDR MSAA cíl ≥ disk okuláru), 6× překryv přes celou obrazovku; oko v ADS = `socket_eye` optiky. Výměna optiky zamyká pušku důvodem jádra `other` (jádro beze změny). Webové varianty GLB (WebP / JPEG 4:4:4) dělá reprodukovatelně `Tools/web_assets/build_web_assets.py`. | Hráč hlásil blikání, rozmazání a plavání tečky: příčiny změřené v `Art/Reference/OPTICS_spec.md` oddíl 11 (světlo záblesku na krytu optiky, bílá tečka z HDR geometrie, zamlžující sklo, adaptivní rozlišení, které na 60 Hz jen klesalo). PNG textury byly pro hostitele Artifact příliš velké. |
| D12 | 2026-09-27 | **Webová verze mapy Kalné Hamry se generuje z dat mapy:** `Tools/level/export_web_level.py` (Python, numpy; zapečení světla přes `mathutils` z modulu `bpy`) čte jen `layout.json` + `buildings.json` a zapisuje `Web/public/assets/levels/kalne_hamry/kh_terrain.glb` (terén 0,5 m pro vykreslení i kolizi, albedo + roughness mapa, rastr povrchů), `kh_world.glb` (budovy, rekvizity, ploty, stromy jako `EXT_mesh_gpu_instancing`, kulisa kopců), `kh_collision.glb` (kolize ve třídách main / move / movevis) a `Web/src/data/kalne_hamry.json`. Ruční úpravy výstupů jsou zakázané (stejně jako D10). Navmesh této mapy se peče z téže kolize (dlaždice 12,8 m, svaření hran dlaždic) a hra ho načítá za běhu (`nav.external`), ne z balíku. | Mapa 350 × 350 m nejde popsat solidy v JSON a zapékat světlo při načtení (0,7 s jen pro zkušební prostor). Kolizní třídy dávají pletivu, oknům a živým plotům správnou průhlednost pro výhled a střely (ART_DIRECTION 6.4, REFERENCE_DECISIONS R-09, R-16). |

## Jednotky a osy

- Blender: metry, Z nahoru. Zbraně: ústí +X, horní strana +Z, pravá strana −Y. Počátek na úchopu pistolové rukojeti.
- glTF / three.js: metry, Y nahoru (exportér glTF převádí Z-up → Y-up). Nikdy neaplikuj měřítko dvakrát.
- FBX pro Unreal: nastavení exportu je zdokumentované v `Art/Source/Blender/lib/ivlib.py`; import do UE je NOT TESTED.

## Adresáře

```
IronValley/
  STATUS.md, QA_REPORT.md, ASSET_MANIFEST.md, README.md
  Docs/            architektura, výtvarné zadání, návrh mapy, půdorysy
  Art/             Blender zdroje (skripty + .blend), textury, exporty FBX/GLB, náhledy
  Shared/          data sdílená mezi webem a UE (testovací vektory, konfigurace pravidel, layout mapy)
  Core/            C++ jádro pravidel + testy (CMake)
  Web/             hratelná verze pro prohlížeč
    src/core/      čistá pravidla (bez three.js), sdílí testovací vektory s C++
    src/engine/    renderer, obloha, světlo, post-processing, načítání assetů
    src/physics/   kolizní svět (BVH), kapslový kontroler, cannon-es svět
    src/player/    hráč, vstup, kamera
    src/weapons/   zbraně, view model, recoil, zásahy
    src/anim/      animace (FPS paže, postavy třetí osoby, IK, ragdoll)
    src/ai/        vnímání, paměť, rozhodování, navigace, kryty
    src/game/      zápas, spawny, výbava, HUD, menu, nastavení, zvuk
    src/level/     načtení mapy, data úrovně, dveře, povrchy
    src/debug/     testovací rozhraní window.__IV (jen pro testy a ladění)
    public/assets/ GLB a data pro runtime
    tests/unit/    node --test
    tests/e2e/     Playwright
  Tools/level/     generátor a kontrola mapy (build_level, nav bake Recast, check_layout, draw_plans, analyze_sightlines)
  Unreal/          projekt UE5 (nezkompilovaný, NOT TESTED)
```

## Pravidla pro kód

- Oddělené systémy, datové definice (JSON) místo jedné obří třídy. Hodnoty z návrhu (rychlosti, munice, skóre, AI prodlevy) jsou v datech.
- Deterministický krok simulace: pevný krok 1/60 s s akumulátorem; vykreslování interpoluje. Logika nesmí záviset na FPS.
- Texty rozhraní česky, krátce.
- Testovací rozhraní `window.__IV` smí číst stav a řídit čas/seed/vstup pro testy; hra na něm nesmí záviset.
