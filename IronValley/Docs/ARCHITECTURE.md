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
  Unreal/          projekt UE5 (nezkompilovaný, NOT TESTED)
```

## Pravidla pro kód

- Oddělené systémy, datové definice (JSON) místo jedné obří třídy. Hodnoty z návrhu (rychlosti, munice, skóre, AI prodlevy) jsou v datech.
- Deterministický krok simulace: pevný krok 1/60 s s akumulátorem; vykreslování interpoluje. Logika nesmí záviset na FPS.
- Texty rozhraní česky, krátce.
- Testovací rozhraní `window.__IV` smí číst stav a řídit čas/seed/vstup pro testy; hra na něm nesmí záviset.
