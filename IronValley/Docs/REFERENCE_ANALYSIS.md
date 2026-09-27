# IRON VALLEY – rozbor referencí uživatele (mapa „Kalné Hamry“)

Stav: 2026-09-27. Zdroj: `Docs/navrhy/01`–`05` (obrázky) a `Docs/navrhy/REFERENCE_PROPS_VEGETATION.md` (R06–R17,
textový popis druhé sady). Rozhodnutí, co z rozboru přešlo do dat a proč, jsou v `Docs/REFERENCE_DECISIONS.md`.
Čísla v tabulkách jsou **odhady z obrázků**. Hodnota v závorce „→ model“ je rozměr, který je v `Shared/level/buildings.json` /
`layout.json` (vygenerováno z `Tools/level/lib/ivbuildings.py` a `build_level.py`).

## 0. Metoda odhadu rozměrů

| Měřítko (kotva) | Předpokládaný rozměr | Kde se dá použít |
| --- | --- | --- |
| Dveře (světlá výška) | 2,0–2,1 m, šířka 0,9–1,0 m | 04 (přístavek, kůlna), 05, 03 (kaple 2,4 m – obloukové) |
| Voják s výstrojí | 1,80 m (v helmě ~1,85 m) | 02, 03 (u zídky, u vozu, na lávce) |
| Jízdní pruh | 3,0–3,25 m (okresní silnice 6,0–6,5 m) | 01, 03 |
| Cihla (délka / výška vrstvy) | 29 cm / 7,5 cm (6,5 + spára) | 04, 05 (obnažené zdivo) |
| Europaleta | 1,20 × 0,80 × 0,144 m | 02, 03 |
| Vojenský nákladní automobil (generický 6×6 s plachtou) | d 7,5–8,0 m, š 2,5 m, v 3,0 m | 01, 03 |
| Sud 200 l | v 0,88 m, ⌀ 0,58 m | 02 |

Postup: v každém obrázku se hledá kotva ve **stejné rovině** jako měřený prvek (fasáda, štít), poměr se odečítá v pixelech
podél hrany rovnoběžné s obrazovou rovinou; u šikmých pohledů se délky v hloubce odhadují přes počet opakujících se prvků
(okna, pole mezi pilastry, pole plotu 2,5 m). **Nejistota:** ±10 % pro výšky a délky rovnoběžné s obrazem, ±15–20 % pro
rozměry v hloubce a pro letecký pohled (01). Všechna rozhodnutí o konečném rozměru se zaokrouhlují na stavební moduly
(zdivo 0,45 / 0,30 m, pole 2,5 / 5,0 m, okna a dveře po 0,05 m).

Barvy: hex hodnoty jsou **mediány vzorků 16 × 16 px** z referencí (ověřeno na kontaktním archu vzorků). Obrázky jsou
v teplém nízkém slunci, proto se albedo pro textury v `ART_DIRECTION.md` bere o 10–20 % odbarvené a posunuté k neutrální.

---

## 1. Reference 01 – letecký pohled na obec (šikmo k severu)

**Co ukazuje:** obec na křižovatce (tvar „Y“ / „T“) dvou asfaltových silnic; potok přitéká ze severu a stáčí se k západu,
tři přechody (most u dílny, lávka na severu, lávka na západě); dílna se dvorem na SZ mezi potokem a lesem; dlouhý sklad se
zeleno-šedou vlnitou střechou a vydlážděným dvorem na SV; kaple v klínu mezi silnicemi; na jihu dvoupodlažní dům s červenou
taškovou střechou v zahradě obehnané zdí; vlevo dole řada garáží a přízemní domky; vpravo dole kamenná chalupa a další domek;
kolem jižní části obce polní cesta (okruh); na SV posečená louka s kulatými balíky, záhumenky; lesy (smrk, borovice, bříza)
na západě a jihu; dřevěné sloupy vedení podél silnic.

| Objekt | Silueta a proporce | Odhad rozměrů | Detaily | Materiály / barvy (vzorek) |
| --- | --- | --- | --- | --- |
| Silnice | dvě větve se setkávají v rozšířené křižovatce (náves) | š 6,0–6,5 m (2 pruhy) ±10 % | středová přerušovaná čára, krajnice, mokrý povrch s kalužemi | asfalt `#464B53` (šedomodrý, mokrý) |
| Sklad | dlouhý obdélník, sedlová střecha nízkého sklonu, na východní straně nižší přístavek s plochou střechou | 45–50 × 14–16 m v leteckém pohledu (±20 %); viz ref. 03 | světlíky/hřebenová větrací lišta, dvůr s paletami, vůz u rampy | střecha `#5F6565` (šedozelený plech), plochá střecha přístavku `#A09E93` |
| Dílna | hala + nižší přístavek + malý přístavek (L) | 22–26 × 9–11 m (±20 %) | 2 komíny, světlík, vrata do dvora | střecha `#5C5854` (tmavý plech) |
| Dům | kompaktní dvoupodlažní blok, valbová střecha, vikýře, nižší křídlo po straně | 11–12 × 9–10 m, hřeben ~10 m (±20 %) | zahrada před domem, zeď s brankou | tašky `#805848` / `#795548` (ve stínu) |
| Zahradní zeď | nízká omítnutá zeď obepínající zahradu | v 1,6–2,0 m | branka v ose domu | omítka `#756B5F` (ve stínu) |
| Kaple | malá loď se zvoničkou nad průčelím | 4–5 × 6–7 m | vysoké stromy vedle (2 × smrk/tuje) | světlá omítka, tmavá střecha |
| Polní cesta | okruh kolem jihu obce | š 2,5–3,0 m | dvě koleje, tráva uprostřed | hlína `#7A6456` |
| Louka / pole | posečené pruhy, balíky | – | kulaté balíky ⌀ 1,5 m | `#7E714B` (sušší tráva) |

**Co obrázek neukazuje:** výškové poměry terénu (jen tušené – les na svazích), zadní strany budov, interiéry, přesnou šířku
potoka, co je za okrajem obrázku. **Interpretace (v modelu):** obec leží v údolí s mírnými svahy (terén −5…+40 m),
okraje mapy tvoří zalesněné ostrohy; plochý přístavek skladu se **nemodeluje** (místo něj zadní dvůr skladu – viz
`REFERENCE_DECISIONS.md` R-03); posečená louka = `FLD_HAY_E`, záhumenky = `FLD_GARDEN_PLOTS`.

---

## 2. Reference 02 – dílna u potoka s betonovou lávkou

**Co ukazuje:** dílnu z ref. 04 v prostředí: dvůr (mokrý beton / štěrk) s paletami, stohy řeziva, sudy, vysokozdvižný vozík,
kanystry; mezi dvorem a potokem betonová opěrná zeď břehu s pletivem na podezdívce (R14); přes potok betonová lávka
se zábradlím z rezavých trubek na betonových sloupcích (R16); vpravo dřevěná čekárna u silnice (R06), sloupy vedení (R07),
mokrá silnice s obrubníky.

| Objekt | Silueta a proporce | Odhad rozměrů (kotva) | Detaily | Materiály / barvy |
| --- | --- | --- | --- | --- |
| Lávka | plochá deska na opěrách, bez oblouku | rozpětí 9–10 m, š 1,6–1,8 m, tl. desky ~0,30 m (voják 1,8 m) → **model BR_FOOT_A/B: deska 0,30, š 1,8** | na jedné straně betonové sloupky 0,25 × 0,25 × 1,0 m po 2 m + 2 trubky (R16) | beton `#979294`, rez |
| Opěrná zeď břehu | svislá betonová zeď, nahoře pletivo | v 1,2–1,5 m nad hladinou, pletivo 1,5 m, sloupky po 2,5 m | spáry bednění, mech | beton `#37332E` (stín) |
| Potok | kamenité koryto, peřeje | š 3–5 m, hloubka vody 0,2–0,4 m | balvany 0,3–0,8 m | voda `#2B2C2C` |
| Dvůr dílny | rovná plocha o jeden stupeň pod podlahou haly | – | kaluže | mokrý beton `#927B6C` |
| Palety, bedny | europalety, stohy 4 ks (R08) | 1,20 × 0,80, stoh 0,6 m | světlé dřevo | `#A57858` |
| Sudy | ocelové (zelené, modré) a plastové modré | 0,88 × ⌀ 0,58 | rez na víku | modrá `#2F5E8C` (odhad) |
| Čekárna | dřevěná, sedlová střecha, lavice (R06) | 3,6 × 2,0 × 2,9 m | vzpěry, patky | šedé dřevo, tmavý plech |

**Co obrázek neukazuje:** druhý břeh u dílny (vzdálenost zdi od budovy), odvodnění dvora, co je pod lávkou.
**Interpretace:** dvůr dílny je o 0,17 m pod podlahou (jeden stupeň u každých dveří); břeh na straně dvora drží nízké betonové
zídky s pletivem `LW_DILNA_BANK_1/2` (0,85 m plná + pletivo do 1,8 m); prostor pod lávkami je nižší než 2,10 m, proto ho
zavírají ocelové česle (`bridges[].underpass`) – žádné průlezy jen v dřepu.

---

## 3. Reference 03 – ulice s kaplí, trafostanicí a skladem

**Co ukazuje:** pohled podél mokré silnice k severu: vlevo dílna (průčelí se dvěma vraty), dřevěná lávka se zábradlím, čekárna
a sloupová trafostanice; vpravo dlouhý sklad z režného cihlového zdiva s omítnutými pilastry, šedými posuvnými vraty a velkými
okny, u něj vojenský nákladní vůz s plachtou, palety; vpravo v popředí kaple se zvoničkou a nízká omítnutá betonová zídka;
dešťová vpusť, kanál, obrubníky; sloupy vedení s pouliční lampou.

| Objekt | Silueta a proporce | Odhad rozměrů (kotva) | Detaily | Materiály / barvy |
| --- | --- | --- | --- | --- |
| Sklad | dlouhá hala, sedlová střecha 15–20°, pilastry dělí fasádu na stejná pole, štít s okny | délka ≈ 3,2 × délka vozu → 24–26 m (±15 %); výška okapu ≈ 1,8 × výška vozu → 5,3–5,8 m; posuvná vrata ≈ 1,3 × výška vozu → 3,9–4,2 m; šířka štítu 12–13 m (±20 %) → **model 25,0 × 12,5 m, okap 5,50, sklon 20°, vrata 3,6 × 4,0** | pilastry ~0,6 m široké, vystupují ~0,15 m; římsa; okna ocelová dělená 6 × 5 tabulí; komín; na hřebeni větrací nástavec | cihla `#674F41` (stín, sazemi tmavá), střecha `#76756B` (šedozelený plech), posuvná vrata `#3F494F` (šedomodrá ocel) |
| Vojenský vůz | 6×6 s plachtou, olivový | 7,5–8,0 × 2,5 × 3,0 m | plachta, rezervní kolo | plachta `#30312A` |
| Kaple | loď se sedlovou střechou, zvonička se stanovou stříškou a křížem nad průčelím | dveře 1,3 × 2,4 (obloukové) → štít ~4,6 m široký; loď 6–7 m; zvonička ~1,6 m čtvercová, vrchol s křížem ~8 m (±15 %) → **model 4,6 × 6,8, okap 3,6, hřeben 5,9, zvonička 1,6 / 8,2** | výklenek se sochou nad dveřmi, okénka zvonice s oblouky | omítka krémová, střecha tmavá |
| Betonová zídka u kaple | nízká, silná, omítnutá, s mechem | v ≈ 0,6 × voják → 1,05–1,15 m, tl. 0,35–0,40 m → **model LW_KAPLE 1,10** | zaoblená koruna | beton `#5C574F` |
| Silnice | dva pruhy, středová čára, okraje | 6,0–6,5 m | kanál, vpusti u obrubníku, kaluže | mokrý asfalt `#4F5258` |
| Trafostanice | transformátor na plošině mezi dvěma sloupy (tvar H) | plošina ~4 m nad zemí, sloupy 8–9 m | izolátory, žebřík, výstražné tabulky | beton, šedý plech |
| Sloupy vedení | dřevěné, konzoly s izolátory, lampa na rameni (R07) | 8,5 m, rozpětí 30–40 m | žluto-černé pruhy u paty | zvětralé dřevo |

**Co obrázek neukazuje:** druhý štít a zadní stranu skladu, nakládací rampu v celé délce, vnitřek skladu, kam vede silnice za
skladem. **Interpretace:** průčelí skladu (strana vrat) je obráceno ke dvoru a silnici B; podél něj betonová nakládací rampa
1,10 m (výška korby) s přístřeškem; dvoje posuvná vrata vpředu (jedna otevřená, jedna zavřená – jak na obrázku), jedna vzadu
otevřená; kancelář v rohu haly se stropem; na trafostanici sedí `S_TRAFO` (`transformer_pole_h`).

---

## 4. Reference 04 – samostatná dílna (hlavní předloha `B_DILNA`)

**Silueta:** půdorys do tvaru L. Hlavní hala se sedlovou střechou, okapová strana (průčelí) k divákovi; vlevo nižší přístavek
se sedlovou střechou rovnoběžnou s halou, **ustupující** za líc haly (je vidět pruh štítové zdi haly mezi rohem přístavku a
rohem haly); vpravo nízká kůlna s pultovou střechou. Nad přístavkem je vidět štít haly s malým okénkem a větracím otvorem.

| Hmota | Proporce z obrázku | Odhad (kotva: dveře přístavku 2,1 m, cihla 29 / 7,5 cm) | → model (`buildings.json`) |
| --- | --- | --- | --- |
| Hala | průčelí ≈ 4,2–4,4 × šířka vrat; okap ≈ 1,35 × výška vrat; hloubka z odkrytého štítu | průčelí 14–15 m, hloubka 9,5–10,5 m, okap 4,4–4,8 m, sklon 28–32° (±10 %) | 14,5 × 10,0 m, zdivo 0,45, okap 4,60, sklon 30°, hřeben 7,49, přesah 0,45 / štít 0,30 |
| Přístavek | 0,45 × délka haly, výška okapu ≈ 1,4 × dveře | 6–7 × 7,5–8 m, okap 2,9–3,1 m, ustoupen o 2 ± 0,5 m | 6,5 × 7,8 m, okap 3,00, sklon 30°, hřeben 5,25, ustoupen o 2,2 m |
| Kůlna (vpravo) | výška ≈ 1,25 × dveře, pultová | 3–4 × 4,5–5,5 m, okap 2,5–2,7 / 3,2–3,4 m | 3,5 × 5,0 m, okap 2,60 / 3,30 (11,3°) |
| Vrata 1 (otevřená) | dvoukřídlá, ≈ 1,6 × výška dveří | 3,3–3,5 × 3,3–3,5 m | `DL_G1` 3,40 × 3,40, křídla otevřena 100° |
| Vrata 2 (zavřená) | dvoukřídlá, užší | 2,5–2,7 × 3,3–3,5 m | `DL_G2` 2,60 × 3,40 (v modelu otevřená – průchodnost, viz rozhodnutí R-02) |
| Okna haly | ocelová, dělená 4 × 6 tabulí | 1,0–1,1 × 1,5–1,7 m, parapet ~1,5 m | 1,0–1,1 × 1,6, parapet 1,5 |
| Okna přístavku | dělená 3 × 4 | 1,0 × 1,5–1,6 m, parapet ~0,9 m | 1,0 × 1,6, parapet 0,9 |
| Komíny | cihlové, hlavice s krycí deskou a otvory | 0,7–0,8 m čtverec, 1,2–1,6 m nad hřebenem | `DL_CH1` 0,75 (vrch 8,11), `DL_CH2` 0,70 (vrch 7,91), vyzděné od vazných trámů 4,25 |
| Světlík | ve střeše pravé poloviny | 0,9 × 1,3 m | `DL_RL1` |

**Detaily:** dvě smaltované kuželové lampy nad vraty na rameni; pozinkované okapy a svody (4 na průčelí haly, 2 na přístavku);
elektrické kabely a trubky po fasádě přístavku; kamenný/betonový sokl ~0,3–0,5 m; ocelový nápis/tabulka u vrat (bez textu).
**Materiály:** vápenná omítka přes cihlové zdivo, z 30–40 % opadaná (hlavně sokl, rohy, pod okapem) – světlá omítka
`#F9E8D2` / `#E3C4A4` (na slunci), stín `#8E7D72`; cihla `#A66145` / `#CC976D`; tmavý vlnitý plech `#514138`–`#52535A`;
vrata rezavá ocel `#B6674C` / `#A96249`; dveře přístavku tmavá ocel `#343437`; okapy pozink `#CDCCC6`; komín cihla `#724538`.

**Co obrázek neukazuje:** zadní fasádu, pravý štít haly (za kůlnou), vnitřek (jen regály za otevřenými vraty), podlahu,
výšku dvora. **Interpretace:** zadní fasáda má dveře a tři okna (v modelu `DL_D2`, `DL_W3`–`W5`); hala je jeden prostor
otevřený do krovu (vazné trámy 4,20 m) s kovárnou (výheň `DL_F10` pod komínem `DL_CH1`) a kamny (`DL_F11` pod `DL_CH2`);
přístavek = výdejna + šatna (strop z prken 2,85 m), kůlna = kompresorovna; podlaha 0,17 m nad dvorem. Horní patro z původního
návrhu bylo odstraněno – obrázek jasně ukazuje jednopodlažní halu.

---

## 5. Reference 05 – samostatná kůlna (předloha „R05“, opakovaná vedlejší budova)

**Silueta:** malá zděná kůlna, pultová střecha klesá k průčelí s dveřmi (okap s žlabem na nízké straně), boční stěna se
šikmou korunou, vysoký betonový sokl.

| Prvek | Odhad (kotva: dveře 0,95 × 2,05 m, cihla) | → model (`secondary_buildings` typ `shed_r05`) |
| --- | --- | --- |
| Půdorys | průčelí ≈ 4 × šířka dveří → 3,6–4,0 m; bok 3,0–3,4 m (±15 %) | 3,8 × 3,2 m |
| Výšky | nízký okap ≈ 1,2 × dveře → 2,4–2,6 m; zadní 3,3–3,5 m | okap 2,5, hřeben (vysoká strana) 3,4 |
| Sokl | 0,30–0,40 m, beton | plinta 0,30 m (+ základ 0,15 pod terénem) |
| Otvory | ocelové dveře, okénko 0,6 × 0,5 m s mříží v boku, žaluziová větrací mřížka 0,4 × 0,3 m, malé okénko 0,3 × 0,4 v průčelí | jen pro vzhled – kůlna je zavřená (dveře zamčené, okna zamřížovaná) |
| Detaily | lampa v kleci nad dveřmi, konce krokví/vaznic pod střechou, pozinkovaný žlab a svod | v `detail` záznamu budovy |

**Materiály:** omítka `#F0D6BD` / `#D2AD90` přes cihlu `#D1845A` / `#6C4836`, sokl beton `#9D8D81` s mechem,
dveře šedomodrá ocel `#9C948E`, střecha rezavý tmavý plech `#665A53`. **Co obrázek neukazuje:** zadní stranu a interiér.
**Interpretace:** kůlna se opakuje jako vedlejší budova (`S_KULNA`, `S_KULNA_DUM`, `S_KULNA_2`, `S_KULNA_3`, `S_PILA_BUDKA`),
vždy **nevstupná** a čitelně zavřená (žádné falešné dveře, které by vypadaly průchodně).

---

## 6. Druhá sada – rekvizity a vegetace (R06–R17)

Podrobný popis je v `Docs/navrhy/REFERENCE_PROPS_VEGETATION.md`. Shrnutí pro data:

| # | Objekt | Rozměr (odhad) | Kolize / průstřelnost / výhled | V datech |
| --- | --- | --- | --- | --- |
| R06 | dřevěná čekárna | 3,6 × 2,0 × 2,9 m | pevná; dřevo průstřelné; lavice nízký kryt | `S_ZASTAVKA` (`bus_shelter_timber`) |
| R07 | sloupy vedení s lampou | 8,5 m, rozpětí 30–40 m | sloup blokuje pohyb (r 0,14 m), výhled ne | `utility_lines` (sloupy, rozpětí, lampy) |
| R08 | bedny a palety | 1,2 × 1,0 × 0,8 / 0,8 × 0,5 × 0,5 / europaleta / stoh 0,6 m | nízký kryt, **průstřelné** (dřevo) | `prop_catalog` (`crate_stack_mixed`, `euro_pallet_stack_4`, …) |
| R09 | trsy trávy | 0,4 / 1,0 / 0,5 m | kosmetické, bez kolize, výhled neblokují | `ground_cover.types` |
| R10 | bříza mladá | 12–15 m | kmen blokuje | `trees.species.briza_mlada` |
| R11 | smrk ztepilý | 20–25 m | kmen blokuje, koruna do země zakrývá | `trees.species.smrk` (jen okraje, ≤ 12 % uvnitř) |
| R12 | listnaté stromy | 8 / 11 m | kmen blokuje | lípa, habr, osika/bříza |
| R13 | keře | 0,8 / 1,3 / 2,0 m | **zakrývají výhled, nezastaví střelu** | `vegetation_blocks`, `ground_cover.shrub_*` |
| R14 | pletivo na podezdívce + branka | 1,5 m (podezdívka 0,35), pole 2,5 m, branka 1,0 m | blokuje pohyb; **průhledné** pro výhled i střelbu (podezdívka kryje do 0,35 m) | `F_SKLAD_ROAD_S/N`, `F_TRAFO` (`chain_link_on_plinth_1p5m`) |
| R15 | bříza vzrostlá | 15–18 m | kmen blokuje | `trees.species.briza` |
| R16 | zábradlí: betonové sloupky + trubky | sloupek 0,25 × 0,25 × 1,0, rozteč 2 m | blokuje pohyb, ne výhled ani střelbu | `BR_MAIN.railing`, `F_RAIL_NAVES` |
| R17 | luční květiny | 0,7 / 0,5 m | kosmetické | `ground_cover.types.yarrow`, `meadow_flower_mix` |

---

## 7. Společné pro všechny reference (atmosféra)

* Doba: pozdní léto / začátek podzimu (žloutnoucí břízy, suchá tráva), **nízké teplé slunce** (dlouhé stíny) a
  **rozpadlá kupovitá oblačnost**; **mokrý asfalt a kaluže** – těsně po dešti.
* Vše zvětralé: omítka opadaná na soklech a rozích, rez na plechu a kování, mech na betonu, špína u země.
* Žádné značky ani čitelné nápisy (v modelu jen fiktivní nápisy, viz `ART_DIRECTION.md` §7).
* **Interpretace / otevřená otázka:** `Web/src/data/environment.json` drží slunce 222° / 38° a jiný typ oblačnosti než reference
  (nižší a pozdější slunce). Ponecháno kvůli čitelnosti (D9), viz `REFERENCE_DECISIONS.md` R-10.
