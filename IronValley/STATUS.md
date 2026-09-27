# IRON VALLEY — stav projektu

Tento soubor čti jako první při každém pokračování práce.

| Položka | Hodnota |
| --- | --- |
| Aktuální fáze | A — dostupnost prostředí (Unreal zablokovaný), B-příprava — ověření pipeline assetů v Blenderu |
| Startovací mapa | Kalné Hamry — webová pracovní verze s provizorní grafikou (generovaná z dat mapy); v UE zatím neexistuje |
| Engine | Unreal Engine 5 — **není k dispozici** (viz tabulka níže) |
| Blender | 4.5.14 LTS jako Python modul `bpy` (PyPI), bez GUI |
| Higgsfield | nepřipojen |
| Datum | 2026-09-27 |

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
- **Integrace 17 botů + nezávislé ověření (2026-09-27, web):** skutečná kola v AI aréně se 3 a 17 boty (Node i sestavená
  hra v Chromiu, vykreslování vypnuté, časově zrychlené) a celé 10min kolo. Nalezené a opravené vady v `src/ai/**`:
  blokace navmeshe kolem známé stěny odřízla tým (měkké / tvrdé blokace), zácpy ve dveřích a uličce (kontakt těl, druhý
  detektor zaseknutí, eskalace), „průlety“ střel skrz zdi, slabý tah na oblast (tlak oblasti), střelba do spoluhráče za cílem,
  slité dávky, přešlapování, boti bojující během odpočtu, detekce o interval dřív. Nový e2e test „celé kolo se 17 boty“
  (`Web/tests/e2e/09_full_round.test.mjs`), telemetrie `window.__IV.telemetry*`. Naměřené hodnoty: `Docs/AI.md` oddíl 11. Poslední úplný běh 2026-09-27:
  **unit 388/388, e2e 73/73 PASS**.

- **Optiky ve webu (2026-09-27):** příčiny blikání a rozmazání změřeny a opraveny (světlo záblesku osvětlovalo kryt optiky,
  záblesk přes sklo, tečka jako HDR geometrie → bílá, hranatá a s paralaxou, zamlžující sklo, adaptivní rozlišení na 60 Hz
  jen klesalo); pět optik na liště IV-7 (vestavěná optika skrytá, mířidla sklopená −90°), 1× kolimovaná síťka (SDF,
  min. velikost, bez zoomu), 2× / 3× obraz v obraze, 6× překryv, citlivost podle zvětšení; výbava s náhradní optikou,
  zbrojní bedny na spawnech obou map, výměna z batohu (B, 3 s), boti podle role s LOD1. Webové varianty assetů
  `Tools/web_assets/build_web_assets.py` (puška 16,6 → 7,0 MiB, optiky 19,3 → 8,8 MiB). Podrobně a čísla:
  `Art/Reference/OPTICS_spec.md` oddíl 11. Poslední běh: **unit 412/412, e2e 82/82 PASS** (SwiftShader). Výkon na GPU NOT TESTED.

- **Kalné Hamry hratelné ve webu (2026-09-27, pracovní verze, provizorní grafika):** mapa se generuje reprodukovatelně
  z `Shared/level/layout.json` + `buildings.json` nástrojem `Tools/level/export_web_level.py` (rozhodnutí D12): terén 0,5 m
  s povrchy (asfalt, štěrk, hlína, bláto, tráva, beton, dlažba, voda), všechny budovy z `buildings.json` (zdi s tloušťkou,
  otvory, ostění, parapety, rámy, sklo, dveře v klidové poloze, podlahy, stropy, schody, střechy, sokly), vedlejší budovy jako
  zavřené objemy, opěrné zdi, mosty s česlemi, ploty (pletivo průhledné pro výhled i střely), fyzická hranice, rekvizity
  jako bloky, 1650 stromů podle druhů; světlo zapečené při generování. Level `kalne_hamry` v nabídce „Kalné Hamry — pracovní
  verze (provizorní grafika)“: 3 týmy, 3 polygonové zóny, řady spawnů podle zóny, 6 zbrojních beden, hranice s odpočtem
  a „Minové pole“, 846 návrhových krycích bodů. Navmesh (Recast, dlaždice svařené) — všechny týmy dosáhnou všech zón.
  Načtení ~1,0–1,2 s, 221 draw callů / 0,65 M trojúhelníků na návsi (se stíny), tik 17 botů 2,3–3,1 ms. Kola se 17 boty
  na všech třech zónách končí vítězem, zaseknutí < 4 s, 0 teleportů. Podrobnosti: `Web/README.md` („Mapa Kalné Hamry“),
  `Docs/AI.md` oddíl 14, testy `tests/unit/kalne_hamry.test.mjs`, `tests/e2e/11_kalne_hamry.test.mjs`.

- **Úvodní menu podle návrhu uživatele (2026-09-27, `Docs/navrhy/06_uvodni_menu_navrh.webp`):** logo IRON VALLEY
  (inline SVG, Barlow Condensed Black, opotřebení filtrem feTurbulence), žlutý pruh, položky HRÁT / VÝCVIK / NASTAVENÍ /
  AUTOŘI / UKONČIT (šipky ↑↓, Home/End, Enter), výběr mapy a odkaz Ovládání pod nimi, popisek „— Kalné Hamry“ vpravo
  dole, nová obrazovka Autoři (hra, knihovny, data, písma, zvuky s licencemi). Pozadí = obrázek z návrhu bez zapečeného
  textu (`Tools/web_assets/clean_title_art.py`). Písma se registrují přes FontFace z bajtů a obrázek se kreslí do canvasu
  z ImageBitmap, takže je CSP hostitele nemůže zablokovat (test s přísnou CSP bez `data:` písem prochází). Akcent celé
  hry sjednocen na žlutou z návrhu (#d6a23e). Pomalý zoom pozadí jsem zkusil a zrušil: v softwarovém vykreslování
  zdržoval hlavní vlákno (20 dotazů 3,5–5 s místo 0,05 s).
  Testy: **unit 421/421 PASS**; plný běh **e2e 85/86**. Jediný pád (SND-01, hra po kliknutí na Výcvik 30 s nereagovala)
  nastal při zátěži ~8 z paralelně běžícího Blenderu (voják). Samostatný opakovaný běh `08_audio`: **3/3 PASS**.

## Náhled pro uživatele

- Soukromý Artifact: https://claude.ai/artifact/5h5KbXu4z4j3Q2SWxGNZgi
  - verze 1 = zkušební prostor (commit eec7150);
  - verze 2 = commit 941b72e: zkušební prostor + AI aréna, kolo 3 týmů se 17 boty (provizorní figuríny), opravy pohybu
    a recoilu, zvuk (licencované nahrávky). Plné kolo se 17 boty v tu chvíli ještě NEověřeno nezávislou kontrolou.
  - verze 3 = commit c92d5be: ověřená kola se 17 boty (12 opravených vad AI), unit 388/388, e2e 73/73.
  - verze 4 = commit 5089134: optiky (holo 1×, kolimátor 1×, hranol 2×, puškohled 3× a 6×), výběr ve výbavě, zbrojní
    bedna, náhradní optika v batohu (B, 3 s); opravené blikání/rozmazání/plavání tečky; unit 412/412, e2e 82/82.
  - verze 5 = commit d80fa81: úvodní menu podle návrhu uživatele (obrazovka Autoři), Kalné Hamry jako hratelná pracovní
    verze (provizorní grafika) v nabídce map, opravená puška IV-7; unit 421/421, e2e 85/86 (SND-01 samostatně 3/3).
    Chování přímo v rámci claude.ai (CSP, pointer lock) stále NOT TESTED.
  - verze 6 = rozpracovaný terén a vegetace Kalných Hamrů (materiály zem, tráva, stromy a keře z Blenderu), budovy
    stále maketa; unit 425/425, e2e mapy + boot 22/22 (plný e2e v tomto stavu NEspuštěn).
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
  **Hotovo ve webu 2026-09-27** (viz „Hotovo“); do náhledu Artifact zatím nepublikováno.
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
- integrace 17 botů a nezávislé ověření herního cyklu a AI: **hotovo 2026-09-27** (viz „Hotovo“);
- zpětná vazba z hraní: pohyb/recoil rozpracovány (traversal.js, stride.js, cameraEffects.js, muzzleEffects.js), zvuk nezačat.
Pokračuje se úsporně: max. 2 agenti na pozadí současně (Agent), bez velkých workflowů.

## Druhé přerušení limitem využití (2026-09-27 ~10:00 → obnoveno 10:20 UTC)

Zastaveni agenti: úprava mapy podle referencí uživatele (checker 82 PASS / 5 FAIL) a ruce/rukavice/úchopy
(uprostřed renderů a exportu). Oba obnoveni se zachovaným kontextem. Hotovo předtím a commitnuto: oprava pušky IV-7
(745251e, specifikace doplněna baef131), optiky ve hře (5089134), náhled v4.

## Pozastaveno uživatelem (2026-09-27 ~17:00 UTC)

Uživatel požádal o zastavení veškeré práce a o verzi k vyzkoušení (náhled v6). Pokračovat až na jeho pokyn.
- **Terén a vegetace (fáze 1 grafiky mapy):** zastaveno během 2. kola kritiky (`Docs/MAP_art_r1_defects.json`,
  `Docs/MAP_art_r2_defects.json`). Hotovo: splat materiál terénu (`Web/src/level/terrainMaterial.js`, generované sady
  `Tools/environment/terrain_textures.py`), tráva (`grass.js`), stromy a keře z Blenderu (`Art/Source/Blender/environment/
  vegetation.py`, `vegetation.js`), testy `tests/e2e/12_map_art.test.mjs`, `tests/unit/map_art.test.mjs`. Otevřené:
  les místy příliš tmavý, tráva nízká / řídká, přechody, závěrečné ověření a zápis do STATUS / manifestu.
- **Voják + ruce v první osobě:** zastaveno uprostřed přestavby podle referencí uživatele (`Docs/navrhy/REFERENCE_SOLDIER.md`,
  `REFERENCE_INGAME.md`): nové moduly `soldier_cloth.py`, `soldier_kit.py` rozpracované, soubory v nekonzistentním stavu.
  Do hry voják zatím NENÍ napojen (boti jsou stále figuríny).
- Čeká na uživatele: povolení domén Poly Haven / ambientCG, volba světla (zataženo / slunečné pozdní léto / obojí).

## Známé vady / otevřené body

- P0 (vnější blokátor): Unreal Engine 5 není v prostředí dostupný → hra v UE nemůže být spuštěna ani testována.
- HF-01: BLOCKED — Higgsfield nepřipojen.
- Zapečení osvětlení běží při načtení jen u zkušebního prostoru a AI arény (~0,7 s); Kalné Hamry mají světlo zapečené
  při generování.
- Chování uvnitř hostitele Artifact na claude.ai (pointer lock, CSP) NOT TESTED; lokálně simulovaná přísná CSP prochází.

## Další krok

Ověřit jeden kompletní průchod pipeline assetu (puška: model → UV → materiály → bake textur → export FBX/GLB → kontrolní rendery
→ zpětný import) a rozhodnout s uživatelem náhradní cestu ke spustitelné verzi.
