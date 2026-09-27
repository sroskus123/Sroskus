# IRON VALLEY — stav projektu

Tento soubor čti jako první při každém pokračování práce.

| Položka | Hodnota |
| --- | --- |
| Aktuální fáze | A — dostupnost prostředí (Unreal zablokovaný), B-příprava — ověření pipeline assetů v Blenderu |
| Startovací mapa | zatím neexistuje |
| Engine | Unreal Engine 5 — **není k dispozici** (viz tabulka níže) |
| Blender | 4.5.14 LTS jako Python modul `bpy` (PyPI), bez GUI |
| Higgsfield | nepřipojen |
| Datum | 2026-09-26 |

## Prostředí, ve kterém se pracuje

Vzdálený cloudový kontejner (Ubuntu 24.04.4 LTS, Linux 6.18, x86_64), 4× Intel Xeon @ 2,1 GHz, 15 GiB RAM, bez swapu,
cca 29 GB volného disku, **bez GPU** (`/dev/dri` chybí, `nvidia-smi` chybí). Síťový přístup omezený politikou prostředí.

## Tabulka dostupnosti (ověřeno 2026-09-26)

| Oblast | Stav | Důkaz / překážka |
| --- | --- | --- |
| Unreal Editor | CHYBÍ | Není nainstalován. `www.unrealengine.com` a `dev.epicgames.com` vrací 403 (síťová politika), `github.com/EpicGames/UnrealEngine` vyžaduje propojený Epic účet. Stroj nemá GPU a má jen ~29 GB volného disku. |
| Build UE (C++ / UBT) | CHYBÍ | `clang 18`, `gcc`, `cmake` jsou k dispozici, ale bez hlaviček enginu a UnrealBuildTool nelze UE modul zkompilovat. Čisté C++ bez UE kompilovat lze. |
| Blender | OVĚŘENO | `pip install bpy==4.5.*` → `bpy 4.5.14 LTS`; testovací render Cycles (CPU) 320×240 za 0,73 s; export FBX (`io_scene_fbx`) i GLB (`io_scene_gltf2`) proběhl. GUI Blenderu není; `download.blender.org` je blokován. |
| Higgsfield | CHYBÍ | V relaci není žádný konektor (`ListConnectors` → prázdné), `higgsfield.ai` vrací 403 (síťová politika), v registru konektorů nebyl nalezen. |
| Import assetů do UE | CHYBÍ | Závisí na Unreal Editoru. |
| Render (kontrola vzhledu) | OVĚŘENO | Cycles CPU render do PNG, obrázky umím prohlížet. Render z Blenderu **neprokazuje** vzhled ve hře. |
| Místní spuštění hry (UE) | CHYBÍ | Bez Unreal Editoru nelze PIE ani Standalone. |
| Prohlížečový test | OVĚŘENO (jen WebGL) | Headless Chromium (Playwright 1.56.1) → WebGL 2.0 přes SwiftShader (softwarově). Pixel Streaming: CHYBÍ (vyžaduje běžící UE aplikaci). |

`localhost` tohoto kontejneru není `localhost` uživatele. Pro náhled uživateli lze použít jen skutečně podporovanou cestu
(soukromý odkaz na Artifact na claude.ai) nebo přesný postup místního spuštění na jeho stroji.

### Nejmenší kroky k odblokování

1. **Unreal:** spustit tuto práci na počítači s nainstalovaným UE 5.x a GPU (Claude Code lokálně / desktopová aplikace), nebo
   v self-hosted prostředí s GPU, UE5 a povoleným přístupem na domény Epic. V tomto cloudovém kontejneru UE5 provozovat nelze.
2. **Higgsfield:** připojit konektor Higgsfield na claude.ai a v nastavení prostředí povolit síťový přístup na domény, ze kterých
   se stahují výstupy generací (a schválit kreditový rozpočet).
3. **Blender GUI:** není potřeba; pipeline běží skripty přes `bpy`.

## Rozhodnutí uživatele (2026-09-26)

- **Hybrid:** hratelná verze pro prohlížeč (three.js/WebGL) z assetů z Blenderu, testovaná zde a předaná jako soukromý odkaz;
  paralelně příprava projektu UE5 (FBX, C++ zdroj, importní skripty) — ten zůstane nezkompilovaný a NOT TESTED.
- **Higgsfield:** pokračovat bez něj; HF-01 = BLOCKED, dokud nebude připojen.
- Technická rozhodnutí a adresáře: `Docs/ARCHITECTURE.md`. Původní zadání: `Docs/zadani/`.

## Hotovo

- Kontrola prostředí a tabulka dostupnosti (výše).
- **Fáze A (web) — základ enginu** (`Web/`): three.js 0.186.1, pevný krok 1/60 s s interpolací, kapslový kontroler (BVH),
  zkušební prostor, hitscan ověřovaný od ústí, obloha/slunce/stíny, zapečené světlo zkušebního prostoru, vstup s pointer lock
  a záložním rozhlížením tažením, `window.__IV` pro testy. Build `npm run build` → `dist/index.html` + `dist/artifact.html`.
  Ověřeno 2 koly nezávislé kontroly: **e2e 39/39 PASS, unit 278/278 PASS** (headless Chromium, SwiftShader). Výkon na reálném GPU: NOT TESTED.
- **Jádro pravidel** (`Web/src/core`, `Core/`, `Shared/`): munice + přebíjení s komorou, kontrolní bod, kolo, respawn.
  JS 217/217, C++ ctest 15/15 (GCC, clang, ASan+UBSan), 149 sdílených vektorů, diferenciální fuzz JS↔C++, 19 injektovaných
  mutací zachyceno. Pravidla a rozhodnutí: `Docs/RULES.md`.

## Náhled pro uživatele

- Soukromý Artifact: https://claude.ai/artifact/5h5KbXu4z4j3Q2SWxGNZgi
  - verze 1 = zkušební prostor (commit eec7150);
  - verze 2 = commit 941b72e: zkušební prostor + AI aréna, kolo 3 týmů se 17 boty (provizorní figuríny), opravy pohybu
    a recoilu, zvuk (licencované nahrávky). Plné kolo se 17 boty v tu chvíli ještě NEověřeno nezávislou kontrolou.
- Hostitel Artifact **neservíruje `.glb`**. Artefaktová verze proto dostává modely jako `<cesta>.glb.b64.txt` (base64 text);
  `src/engine/assets.js` je dekóduje sám a volá `GLTFLoader.parse` (bez blob:/data: URL). Ověřeno lokálně v Chromiu,
  0 chyb, puška s texturami. Převedeno do hlavního buildu: `npm run build` vytvoří i `Web/dist-artifact/`
  (publikovat `iron-valley.html` + všechny soubory složky). TODO: zmenšit GLB (WebP textury).
- Publikační složka: `scratchpad/publish/iron-valley.html` (stejná cesta = stejná URL při dalších verzích).

## Zpětná vazba uživatele z hraní náhledu (2026-09-26 ~20:30)

Běží WF `iv-feel-feedback` (pohyb/kamera, recoil, zvuk) a `iv-optics-art` (modely optik). Po nich webová integrace optik.
- Klouzání při prudké změně směru běhu → oprava modelu zrychlení/tření (měřitelná kritéria).
- Skok těsně před dopadem (buffer) a chvíli po sejití z hrany (coyote); skok za běhu/sprintu.
- Chyba: sprint → skok → přikrčení ve vzduchu = zastavení na místě.
- Přeskok/přelezení zdi 1 m (vault/mantle) s validací kolizí, události pro animaci rukou.
- Jemný pohyb kamery na schodech a při krocích (škálováno nastavením).
- Viditelný recoil, záblesk, nábojnice; zvuky (jen ověřené licence CC0/PD/CC-BY, jinak syntéza označená jako prozatímní), ne zbytečně hlasité.
- Optika: blikání při výstřelu a rozmazání (sklo s transmisí), tečka plave s pohybem, zbytečná železná mířidla →
  čisté holo/kolimátor, 2×, 3×, 6×; výběr ve výbavě, zbrojní bedna na spawnu, náhradní optika v batohu (výroba/crafting ne).
- Nohy pod sebou nevidět → vyřeší plné tělo v první osobě po dokončení postav a animací.

## Přerušení limitem využití (2026-09-26 ~22:00 → obnoveno 2026-09-27 00:20 UTC)

Všech 6 běžících workflowů se zastavilo na limitu využití; kontejner se restartoval, soubory zůstaly.
Stav po obnovení: build OK, unit 368/368 PASS, e2e běží. Nedokončené a neověřené zůstaly:
- puška: oprava r1 (otevřené P1: napínací páka, sklopení hledí do riseru, „plovoucí“ dioptr, materiál eloxu vs polymer,
  chybějící opotřebení hran, AO krytu okénka zapečené v otevřené poloze);
- mapa: oprava r1 po kritice (otevřené P1: fyzická hranice mapy, rampa/schody u skladu v terénu, uzavřené budovy
  bez podkladů, 5m svah za skladem, okapy nad hranou střechy, krycí body AI uvnitř budov); checker 73/73 je chceme zpřísnit;
- základ postavy: P1 klouby prstů u hřbetu (pěst proráží hřbet ruky) + P2;
- ruce/rukavice, pistole, převod pohybů CMU, optiky: rozpracováno/nezačato;
- integrace 17 botů a nezávislé ověření herního cyklu a AI: nedokončeno;
- zpětná vazba z hraní: pohyb/recoil rozpracovány (traversal.js, stride.js, cameraEffects.js, muzzleEffects.js), zvuk nezačat.
Pokračuje se úsporně: max. 2 agenti na pozadí současně (Agent), bez velkých workflowů.

## Známé vady / otevřené body

- P0 (vnější blokátor): Unreal Engine 5 není v prostředí dostupný → hra v UE nemůže být spuštěna ani testována.
- HF-01: BLOCKED — Higgsfield nepřipojen.
- Munice ve webu (`src/weapons/weaponState.js`) ještě není napojená na autoritativní jádro `src/core/weapon.js` — napojit ve fázi C.
- Zapečení osvětlení běží při načtení (zkušební prostor ~0,7 s); pro mapu 350 × 350 m přesunout do buildu.
- Chování uvnitř hostitele Artifact na claude.ai (pointer lock, CSP) NOT TESTED; lokálně simulovaná přísná CSP prochází.

## Další krok

Ověřit jeden kompletní průchod pipeline assetu (puška: model → UV → materiály → bake textur → export FBX/GLB → kontrolní rendery
→ zpětný import) a rozhodnout s uživatelem náhradní cestu ke spustitelné verzi.
