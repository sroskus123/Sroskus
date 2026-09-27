# IRON VALLEY — předávací dokument (stav 2026-09-27 večer)

Tento dokument je pro **nový chat / nového vývojáře**, který na projekt naváže. Shrnuje, co se dělalo, na čem,
jaká padla rozhodnutí, co je hotové, co rozpracované, všechny reference a zpětnou vazbu uživatele. Podrobnosti jsou
v odkazovaných souborech. Pracovní jazyk s uživatelem je **čeština**.

- **Repozitář:** https://github.com/sroskus123/Sroskus (veřejný). Celý projekt je ve složce `IronValley/`.
  Zbytek repozitáře (kořenový `index.html`, `script.js`, `styles.css`, `CNAME`, `.github/workflows/static.yml`)
  je uživatelův web na GitHub Pages z větve `main`. Nesahat na něj.
- **Větev s prací:** `claude/new-session-sqnojt`. Do `main` nic sloučeno není a žádný pull request neexistuje.
  - Stažení jako ZIP: https://github.com/sroskus123/Sroskus/archive/refs/heads/claude/new-session-sqnojt.zip
  - Klon: `git clone -b claude/new-session-sqnojt https://github.com/sroskus123/Sroskus.git`
- **Hratelný náhled (soukromý Artifact na claude.ai, účet uživatele):** https://claude.ai/artifact/5h5KbXu4z4j3Q2SWxGNZgi
  (verze 6). Aktualizuje se jen publikací se stejnou URL, viz oddíl 10.

## 0. Pořadí čtení pro nový chat

1. Tento soubor.
2. `STATUS.md`: průběžný stav, tabulka dostupnosti prostředí, verze náhledu, co bylo pozastaveno.
3. `Docs/zadani/01_HLAVNI_PROMPT_UE5.md` a `02_PRAVIDLA_KVALITY_A_TESTY.md`: původní zadání uživatele (závazné).
4. `Docs/ARCHITECTURE.md`: deník rozhodnutí D1–D12, jednotky, adresáře, pravidla pro kód.
5. `Docs/GAMEPLAY_CONTRACTS.md`, `Docs/RULES.md`, `Docs/AI.md`: kontrakty hry, pravidla, AI.
6. `Docs/ART_DIRECTION.md`, `Docs/MAP_DESIGN.md`, `Docs/REFERENCE_*.md`, `Docs/navrhy/*.md`: výtvarný směr a reference.
7. `ASSET_MANIFEST.md`: každý asset (autor, licence, zdroj, exporty, stav QA).
8. Specifikace assetů v `Art/Reference/*_spec.md`: puška, optiky, lidské tělo, ruce, voják.

## 1. Co je IRON VALLEY (zadání v kostce)

Původní realistická vojenská FPS inspirovaná žánrem hry **WARDOGS**. Nesmí z ní nic kopírovat: žádná jména, modely,
rozhraní ani mapy. Zadání požaduje **vertical slice v Unreal Engine 5**:
- 3 týmy × 6 (hráč + 17 botů), jedna kontrolní oblast (3 možná místa), kolo 10 minut nebo do 100 bodů;
- puška a potom pistole; 3 typy budov, z toho ≥ 2 s průchozím interiérem; mapa údolí ~350 × 350 m;
- priority kvality: dobré modely, textury, ruce a prsty, přirozené animace, smysluplná AI, fyzika, věrohodné budovy;
- poctivé hlášení výsledků PASS / FAIL / NOT TESTED / BLOCKED, `QA_REPORT.md`, manifest assetů;
- použití Higgsfield (HF-01).

## 2. Rozhodnutí uživatele a jeho preference

| Kdy | Rozhodnutí |
| --- | --- |
| 2026-09-26 | **Hybrid:** hratelná verze v prohlížeči (WebGL, three.js) se staví a testuje tady, projekt UE5 se připravuje (FBX, C++ jádro) k dokončení na stroji s UE5. Důvod: v cloudovém kontejneru není GPU, domény Epic jsou blokované a je málo disku (D1). |
| 2026-09-26 | **Higgsfield:** pokračovat bez něj (není připojený, doména blokovaná). HF-01 = BLOCKED (D2). |
| 2026-09-26 | Uživatel na začátku zapnul „ultracode“ (velké workflowy); později vypnuto. Po dvou výpadcích na limitu využití se jede úsporně: **max. 2 agenti na pozadí současně**, žádné velké workflowy bez výslovného svolení. |
| průběžně | Chce vidět průběžné výsledky (snímky), mluví česky, oceňuje upřímnost. Jeho měřítko kvality je **WARDOGS** (viz reference 11–14). |
| 2026-09-27 | Úvodní menu podle jeho návrhu (reference 06): schváleno a postaveno. |
| 2026-09-27 večer | „Zastav vše, udělej poznámky, dej vše na GitHub, předám to jinému chatu.“ Všechny agenty jsou zastavené. |

## 3. Co se dělalo (časová osa podle commitů)

| Commit | Co |
| --- | --- |
| `191364c` | Kontrola prostředí, rozhodnutí uživatele, architektonický kontrakt |
| `eec7150` | Fáze A: webový engine (three.js, pevný krok 1/60 s, kapslový kontroler, hitscan od ústí, obloha / stíny, `window.__IV` pro testy) + jádro pravidel v JS a C++ se sdílenými testovacími vektory |
| `86f9282` | Náhled v1 (zkušební prostor) jako soukromý Artifact |
| `1af373e` | Opravy z první hratelnosti: klouzání v zatáčkách, třes na schodech, buffer a coyote skoku, přelézání a přeskok zdi 1 m, chyba sprint → skok → dřep, viditelný zpětný ráz, záblesk, nábojnice |
| `02dd134` | Zvuk: licencované nahrávky CC0 / CC BY, prostorový AudioSystem, ne příliš hlasité |
| `941b72e` | Varianta buildu pro hostitele Artifact (odmítá `.glb`, proto base64 `.b64.txt`) |
| `c92d5be` | 17 botů ve hře, ověřená kola, 12 opravených vad AI |
| `12a049e`, `5089134` | Optiky: holo 1×, kolimátor 1×, hranol 2×, puškohled 3× a 6×; síťky bez paralaxy, obraz v obraze pro 2× / 3×, překryv pro 6×, výběr ve výbavě, zbrojní bedna, náhradní optika v batohu (klávesa B). Náhled v4 |
| `41ef9a5`, `a5052cc` | Reference uživatele (vesnice, dílna, ulice s kaplí a skladem, kůlna); mapa Kalné Hamry přepracována podle nich |
| `745251e`, `baef131` | Puška IV-7: opravy po revizi (páka, sklopná mířidla, materiály, opotřebení) |
| `ea79b8b` | Ruce: oprava kloubů prstů, taktické rukavice (coyote / černé), 13 úchopů napasovaných na IV-7 |
| `29f1dae` | Kalné Hamry hratelné ve webu (maketa s provizorní grafikou) |
| `d80fa81` | Úvodní menu podle návrhu uživatele, obrazovka Autoři, CSP-bezpečné načítání písem a obrázku. Náhled v5 |
| `e7dc165`, `cf0ecdb` | Reference vojáka a snímky z WARDOGS (jen popis, obrázky nejsou v repozitáři) |
| WIP commity | Rozpracovaná grafika mapy (terén, tráva, stromy) a přestavba vojáka, snímky stavu agentů |
| `9136cc4` | Pozastavení na žádost uživatele; náhled v6 (rozpracovaný terén a vegetace) |

## 4. Na čem se pracuje (technologie a nástroje)

| Oblast | Nástroj / knihovna | Poznámka |
| --- | --- | --- |
| Hra v prohlížeči | three.js 0.186.1, three-mesh-bvh 0.9.15 (kolize, paprsky), cannon-es 0.20.0 (dveře, drobná fyzika), three-pathfinding 1.3.0 | Čistý JavaScript **bez WebAssembly** (D3). Build `esbuild` (`Web/tools/build.mjs`). |
| Navigace AI | recast-navigation (jen v Node při buildu), navmesh jako JSON | D4. Kalné Hamry: dlaždice 12,8 m, načítá se za běhu. |
| Pravidla hry | JS (`Web/src/core`) + C++ (`Core/`, CMake, GCC / clang, ASan + UBSan) | Obě implementace procházejí stejné vektory `Shared/testvectors/*.json` + diferenciální fuzz (D6). C++ jádro je určené pro modul UE5. |
| Modely a textury | **Blender 4.5.14 LTS jako Python modul `bpy`** (bez GUI, Cycles CPU) | Vše skripty, deterministicky. Knihovny `Art/Source/Blender/lib/` (`ivlib.py` export a validace, `ivchar.py` postava, `ivhands.py` ruce, `ivoptics.py` sklo a síťky, `ivsoldier.py` oblečení a výstroj, `ivveg.py` vegetace). Exporty FBX (UE, cm) + GLB / glTF (web). |
| Webové varianty assetů | `Tools/web_assets/build_web_assets.py` (`npm run assets:web`) | Textury WebP / JPEG, menší GLB. |
| Mapa | Python + numpy: `Tools/level/run_pipeline.py` → `Shared/level/layout.json` + `buildings.json`; kontrola `check_layout.py` (86 PASS / 0 FAIL / 3 WARN); export do webu `export_web_level.py` (D10, D12) | Ruční úpravy výstupů jsou zakázané, vše jde přes generátor. Půdorysy a plány: `Docs/img/`. |
| Terén a vegetace (rozpracované) | `Tools/environment/*.py` (generované sady textur), `Art/Source/Blender/environment/vegetation.py` (stromy, keře), `Web/src/level/terrainMaterial.js`, `grass.js`, `vegetation.js` | Textury generované procedurálně, protože knihovny CC0 fotografických textur jsou v síti prostředí zablokované. |
| Zvuk | `Tools/audio/` (stažení, zpracování), zdroje a licence `Shared/audio/SOURCES.md`, `Tools/audio/sources.json` | 98 MP3, 41 zvukových klíčů, jen CC0 / CC BY. Autoři jsou v obrazovce Autoři. |
| Lidské tělo | MakeHuman / MPFB2 (CC0), převzato z PyPI balíčku `anny` 0.6.0 | 57 kostí, `SK_Human_Base`. |
| Písma | Barlow Condensed (SIL OFL 1.1) z npm `@fontsource/barlow-condensed` | Menu a logo. |
| Úvodní obrázek | Návrh uživatele, zapečený text odstraněn skriptem `Tools/web_assets/clean_title_art.py` (OpenCV v samostatném venv) | Původ obrázku (Higgsfield?) uživatel zatím nepotvrdil. |
| Testy | `node --test` (unit), Playwright + headless Chromium se SwiftShaderem (e2e) | Časy ze SwiftShaderu nejsou výkon na GPU. |
| Publikace náhledu | Nástroj Artifact v Claude Code (soukromá stránka na claude.ai) | Viz oddíl 10. |

## 5. Struktura složky `IronValley/`

```
HANDOFF.md            tento dokument
STATUS.md             průběžný stav (číst jako první při pokračování)
ASSET_MANIFEST.md     manifest assetů (autor, licence, zdroje, exporty, QA)
Docs/
  zadani/             původní zadání uživatele (2 soubory, závazné)
  ARCHITECTURE.md     rozhodnutí D1–D12, jednotky, adresáře
  GAMEPLAY_CONTRACTS.md, RULES.md, AI.md, MAP_DESIGN.md, ART_DIRECTION.md
  REFERENCE_ANALYSIS.md, REFERENCE_DECISIONS.md (R-01..R-18 + otevřené otázky mapy)
  MAP_review_r1_defects.json, MAP_art_r1_defects.json, MAP_art_r2_defects.json (záznamy revizí)
  img/                plány mapy a budov (PNG)
  navrhy/             reference uživatele 01–06 (.webp) + popisy REFERENCE_*.md
Art/
  Source/Blender/     generátory (.py) + scény (.blend): weapons/ (IV-7, optiky), characters/ (tělo, ruce, voják), environment/ (vegetace), lib/
  Reference/          specifikace assetů *_spec.md
  Textures/           zdrojové textury (PNG 2048², sady Environment)
  Export/             FBX (pro UE) + GLB / glTF (pro web)
  Previews/           kontrolní rendery (v gitu jen výběr v Art/Previews/_handoff/, viz oddíl 12)
Shared/               data sdílená webem a UE: config (rules, ai, optics), level (layout, buildings, terén), testvectors, audio
Core/                 C++ jádro pravidel + testy (CMake)
Tools/                level/ (mapa), environment/ (terén, vegetace), audio/, web_assets/
Web/                  hra v prohlížeči (src/, public/assets/, tests/, tools/), README.md
```

Složka `Unreal/` **zatím neexistuje**. Projekt UE5 se nezaložil, protože UE5 tu není. Pro UE jsou připravené jen
FBX exporty a C++ jádro pravidel.

## 6. Stav po oblastech

| Oblast | Stav | Důkaz / poznámka |
| --- | --- | --- |
| Webový engine, pohyb, kamera, střelba | **Hotovo, ověřeno** | e2e + unit; pohyb a pocit ze zbraně upraveny podle hratelnosti |
| Pravidla (munice, oblast, kolo, respawn) | **Hotovo, ověřeno** (JS + C++) | vektory, fuzz, ctest 15/15 |
| AI, 17 botů, 3 týmy, celé kolo | **Hotovo, ověřeno** | `Docs/AI.md`, e2e `09_full_round`; boti jsou ale **figuríny bez animací** |
| Zvuk | **Hotovo** | `Shared/audio/SOURCES.md` |
| Optiky (5 kusů) ve hře | **Hotovo, ověřeno** | `Art/Reference/OPTICS_spec.md` oddíl 11 |
| Puška IV-7 (model, LOD, textury, FBX / GLB) | **Hotovo** | `Art/Reference/IV7_carbine_spec.md` |
| Pistole IV-P9 | **Nezačato** | ve hře provizorní model |
| Lidské tělo `SK_Human_Base` | **Hotovo** (Blender) | `HUMAN_BASE_spec.md` |
| Ruce a rukavice, 13 úchopů | **Hotovo** (Blender), ve hře **nenapojené** | `HANDS_spec.md` |
| Voják `SK_Soldier` + ruce v 1. osobě | **Rozpracované, zastavené uprostřed přestavby** | Poslední úplný export (před přestavbou) je v `Art/Export/*/Soldier*`, `FP_Arms*`. Uživatel ho **odmítl**: maskáč vypadal jako obarvená kůže a paže byly moc hubené. Přestavba podle referencí 07–14 začala (`soldier_cloth.py`, `soldier_kit.py`), soubory jsou v **nekonzistentním stavu**; `soldier.blend` je mezistav. Ve hře voják **není**. |
| Mapa Kalné Hamry: rozložení, budovy, kryty, navigace | **Hotovo** (maketa) | checker 86 / 0 / 3, kola se 17 boty OK |
| Mapa: grafika fáze 1 (terén, tráva, stromy, keře) | **Rozpracované** (zastavené ve 2. kole oprav) | Náhled v6; e2e mapy 22 / 22; otevřené: les místy tmavý, tráva nízká / řídká (`Docs/MAP_art_r2_defects.json`) |
| Mapa: grafika budov (fáze 2), rekvizity (fáze 3), obloha a světlo (fáze 4) | **Nezačato** | budovy jsou šedé / barevné bloky |
| Úvodní menu, obrazovka Autoři | **Hotovo** | e2e UI-01 |
| Animace postav (chůze, běh, skok, přelézání, míření, přebíjení), ragdoll, animace rukou v 1. osobě | **Nezačato** | plán: motion capture CMU (volně použitelné, zrcadlo `raw.githubusercontent.com/una-dinosauria/cmu-mocap`), retarget na 57 kostí |
| Plné tělo v první osobě (vidět nohy) | **Nezačato** | po vojákovi a animacích |
| Projekt UE5 | **Nezačato / BLOCKED** | UE5 v prostředí nejde spustit |
| `QA_REPORT.md` podle přílohy zadání | **Nevytvořen** | podklady jsou ve STATUS, specifikacích a testech |

Poslední úplný běh testů: **unit 421/421, e2e 85/86** (náhled v5). Jediný pád byl časový limit při zátěži
z Blenderu; samostatně prošel 3/3. Pro stav v6: unit 425/425, e2e mapy + boot 22/22. Plný e2e pro v6 **nespuštěn**.

## 7. Reference (všechny)

### 7.1 Zadání
- `Docs/zadani/01_HLAVNI_PROMPT_UE5.md`, `Docs/zadani/02_PRAVIDLA_KVALITY_A_TESTY.md`

### 7.2 Návrhy uživatele (jsou v repozitáři)
| Soubor | Obsah |
| --- | --- |
| `Docs/navrhy/01_letecky_pohled_vesnice.webp` | Letecký pohled na údolí a vesnici (silnice, potok, sloupy vedení, lesy) |
| `Docs/navrhy/02_dilna_potok_lavka.webp` | Dílna u potoka s lávkou, plot s pletivem na podezdívce, zábradlí |
| `Docs/navrhy/03_ulice_kaple_sklad.webp` | Ulice s kaplí a cihlovým skladem, mokrý asfalt |
| `Docs/navrhy/04_dilna_samostatne.webp` | Samostatná dílna (vrata DL_G2) |
| `Docs/navrhy/05_kulna_samostatne.webp` | Kůlna |
| `Docs/navrhy/06_uvodni_menu_navrh.webp` | Návrh úvodního menu (postaveno) |
| `Docs/navrhy/REFERENCE_PROPS_VEGETATION.md` | Druhá sada obrázků uživatele (rekvizity a vegetace R06–R17). Obrázky se na disk nedostaly, jsou zapsané jako přesný textový popis s rozměry. |
| `Docs/REFERENCE_ANALYSIS.md`, `Docs/REFERENCE_DECISIONS.md` | Rozbor referencí 01–05 a rozhodnutí R-01..R-18 |

### 7.3 Cizí obrázky jako měřítko kvality (NEjsou v repozitáři)
Repozitář je veřejný. Tyto obrázky jsou cizí práce (snímky ze hry WARDOGS, modely vojáků z internetu), proto se do něj
nenahrávají, aby se nešířily. Uživatel je má u sebe a může je poslat znovu. V repozitáři je jejich podrobný popis:
- `Docs/navrhy/REFERENCE_SOLDIER.md`: 07–10, voják v digitálním maskáči a voják v jednobarevné výstroji s nosičem plátů
  (volné oblečení se záhyby, mohutná výstroj, silné paže).
- `Docs/navrhy/REFERENCE_INGAME.md`: 11–14, snímky z WARDOGS (ruce v rukavicích v 1. osobě, mokré blato a smrkový les,
  míření kolimátorem, postava v košili s kapsami a chrániči kolen).

### 7.4 Plány a výkresy (vygenerované)
- `Docs/img/map_plan.png`, `map_plan_core.png`, `map_routes.png`, `plan_dilna_L0.png`, `plan_dum_L0.png`, `plan_dum_L1.png`,
  `plan_sklad_L0.png`, `reference_vs_plan.png`

## 8. Zpětná vazba uživatele (chronologicky, zkráceně)

1. **Hratelnost náhledu:** klouzání při změně směru, třes kamery na schodech, nejsou vidět nohy, skok jen ve stoje a ne
   těsně před dopadem, nejde přelézt zeď 1 m (a chybí animace rukou), chybí zpětný ráz a zvuky („klidně nějaký
   stáhni z internetu, ale něco, co bude pasovat na tu zbraň, a ať to není moc zbytečně hlasitý“), chyba sprint → skok
   → Ctrl = zastavení. **Vše opraveno, kromě nohou** (čeká na plné tělo).
2. **Optiky:** blikání při střelbě v ADS, rozmazání při zoomu, tečka plave s pohybem, zbytečná železná mířidla s optikou;
   chce čisté holo nebo výměnu: blízká, 2–3× a 6× odstřelovací, výběr přes batoh nebo stanoviště. **Hotovo.**
3. **Reference mapy (01–05 + rekvizity a vegetace):** zapracováno do mapy Kalné Hamry. Další připomínky k mapě
   uživatel řekne, „až bude přímo v mapě“.
4. „To je dobré, hlavně to bojování s AI.“ Ví, že modely zbraní a postav se ještě dělají.
5. **Úvodní menu (06):** schváleno, postaveno.
6. **Terén mapy:** „doufám, že to, co tam je teď, tak nezůstane“ (blobové stromy, plochá zelená). Rozběhla se fáze 1.
7. **Voják:** „maskáče vypadají jako součást modelu, jako jen obarvená kůže, ne jako oblečení, a ruce vypadají, jako by
   měl anorexii“, s referencemi 07–10. Přestavba začala.
8. **Snímky z WARDOGS (11–14):** „takhle si představuji, aby to vypadalo ve hře, jak animace, tak celkově vše.“
9. Poslal odkaz na podmínky Poly Haven API a dokumentaci API. Podmínky použití jsou v pořádku (CC0, API zdarma i komerčně,
   vlastní User-Agent), ale servery jsou v síti prostředí **stále zablokované**.
10. Zeptal se, jestli umím pracovat v Unreal Enginu. Odpověď: ano, ale ne v tomto cloudovém prostředí; na jeho PC s UE5 ano.
11. „Zastav vše, udělej poznámky, dej vše na GitHub ke stažení, předám to jinému chatu. Sepiš, co jsi dělal, na čem
    jsi dělal, dej tam všechny reference a úplně vše.“

## 9. Otevřené otázky pro uživatele

1. **Unreal Engine:** má počítač s UE5 (nebo ho může nainstalovat) a jakou grafiku? Doporučení: pokud ano, přesunout hlavní
   vývoj do UE5 na jeho PC (Claude Code spuštěný lokálně) a web nechat jako rychlý náhled. Orientačně: Windows,
   GPU s 8 GB VRAM (RTX 3060), 32 GB RAM, ~150 GB SSD.
2. **Světlo a nálada:** zataženo a mokro (jako WARDOGS), slunečné pozdní léto (jako jeho návrhy a úvodní obrázek),
   nebo obojí (náhodně nebo na výběr)?
3. **Domény pro fotografické textury:** povolit v nastavení prostředí `ambientcg.com`,
   `acg-download.struffelproductions.com`, `polyhaven.com`, `api.polyhaven.com`, `dl.polyhaven.org`
   (menu prostředí v záhlaví relace → Edit → Network access).
4. **Úvodní obrázek:** jak vznikl, a byl to Higgsfield (HF-01)?
5. **Mapa** (`Docs/REFERENCE_DECISIONS.md`, „až bude v mapě“): čas a oblačnost; délka skladu 25 m, nebo delší hala
   s přístavkem; jméno „Kalný potok“; vrata dílny `DL_G2` otevřená, nebo zavřená.

## 10. Jak sestavit, testovat a publikovat

```
cd IronValley/Web
npm install                  # jen při prvním spuštění (node_modules nejsou v gitu)
npm run build                # navmesh + dist/ (index.html, artifact.html) + dist-artifact/ (verze pro claude.ai)
npm run serve                # lokální server nad dist/ (pak otevřít vypsanou adresu v prohlížeči)
npm run test:unit            # node --test
npm run test:e2e             # Playwright (Chromium + SwiftShader), plná sada trvá ~25 min
```
- Mapa: `python3 Tools/level/run_pipeline.py` (data), `python3 Tools/level/check_layout.py` (musí být 0 FAIL),
  `python3 Tools/level/export_web_level.py` (GLB pro web; potřebuje `bpy`).
- Assety: každý generátor v `Art/Source/Blender/**.py` má v hlavičce příkaz a etapy (např. voják:
  `python3 Art/Source/Blender/characters/soldier.py --stages build,uv,textures,lods,fp_tex,validate,render,export`).
- C++ jádro: `cmake -S Core -B Core/build && cmake --build Core/build && ctest --test-dir Core/build`.
- **Publikace náhledu:** zkopírovat `Web/dist-artifact/` do stálé složky a publikovat `iron-valley.html` nástrojem Artifact
  s `root` = ta složka, `files` = všechny ostatní soubory složky a `url` = https://claude.ai/artifact/5h5KbXu4z4j3Q2SWxGNZgi
  (stejná URL = nová verze). Limity: ≤ 64 MB a ≤ 255 souborů na jednu publikaci, soubor < 16 MB. v6 má 58 MB a 135 souborů.

## 11. Úskalí prostředí (naučeno za pochodu)

- `bpy` potřebuje **numpy < 2** (1.26.x). Nikdy neinstalovat globálně balíček, který numpy povýší (stalo se s OpenCV).
  Jiné balíčky dávat do venv.
- Hostitel Artifact **neservíruje `.glb`** (ani s jiným typem obsahu). Proto build píše `<soubor>.b64.txt` a
  `Web/src/engine/assets.js` si je dekóduje. Obrázky se dekódují přes `createImageBitmap(Blob)` bez blob: URL, písma přes
  `FontFace(ArrayBuffer)`. Přísná CSP hostitele tak nic nezablokuje; hlídá to test v `01_boot`.
- Nekonečné CSS animace přes velké plochy v SwiftShaderu blokují hlavní vlákno a rozbíjejí časové testy. Pomalý zoom
  pozadí menu byl proto zrušen.
- Blender (Cycles CPU) na 4 jádrech zpomaluje souběžné e2e testy. Časově citlivý pád vždy zopakovat samostatně.
- `pkill -f` s podřetězcem může zabít vlastní shell; používat PID soubory.
- Síť: npm, PyPI a raw.githubusercontent.com fungují; ambientCG, Poly Haven a Epic jsou zablokované (proxy 403).
- Po každém tahu vyžaduje hook commit a push všech změn. Rozpracovanou práci agentů commitovat jako „WIP“.
- Limity využití: dvakrát zastavily všechny agenty. Soubory přežily a agenti šli obnovit se zachovaným kontextem.

## 12. Co je a není na GitHubu

- **Je:** veškerý kód, data mapy, dokumentace, reference uživatele 01–06, webové assety (`Web/public/assets`, včetně
  GLB mapy, pušky, optik a vegetace), zvuky, písma. Od tohoto předání také **FBX / GLB exporty** (`Art/Export/`),
  **zdrojové textury** (`Art/Textures/`), **scény Blenderu** (`*.blend`, bez záloh `*.blend1`) a výběr kontrolních renderů
  jako JPEG v `Art/Previews/_handoff/`.
- **Není:** cizí referenční obrázky 07–14 (viz 7.3), buildy `Web/dist*` (vytvoří `npm run build`), `node_modules`,
  úplná sada kontrolních renderů PNG (~0,5 GB, vytvoří je generátory), PNG kopie referencí 01–05 (stejný obsah jako `.webp`).

## 13. Doporučené další kroky

1. Zeptat se uživatele na otázky z oddílu 9, hlavně na UE5 a světlo.
2. **Pokud UE5 na PC:** založit projekt UE5 (C++), importovat FBX (puška, optiky, ruce, voják), převést pravidla z
   `Core/`, postavit mapu z `Shared/level/*.json`. Pro animace zvážit Game Animation Sample od Epicu (motion matching)
   a MetaHuman. Web udržovat jako náhled.
3. **Pokud dál web:** dokončit přestavbu vojáka (reference 07–14, měřitelné cíle v `REFERENCE_SOLDIER.md`: paže
   s rukávem 38–42 cm obvodu), napojit vojáka a ruce do hry místo figurín, animace z CMU mocapu, dokončit fázi 1 grafiky
   mapy a pak fáze 2–4, pistoli IV-P9, `QA_REPORT.md`.
