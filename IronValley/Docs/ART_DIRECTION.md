# IRON VALLEY – výtvarný směr mapy „Kalné Hamry“

Stav: **závazné** pro tvůrce assetů (Blender skripty), pro webový renderer (three.js) a pro pozdější přenos do UE5.
Datum: 2026-09-27 (revize podle referencí uživatele `Docs/navrhy/01`–`05` a R06–R17; rozbor v `Docs/REFERENCE_ANALYSIS.md`,
rozhodnutí v `Docs/REFERENCE_DECISIONS.md`). Související data: `Shared/level/layout.json`, `Shared/level/buildings.json`, `Web/src/data/environment.json`,
`Web/src/data/teams.json`. Návrh mapy a herní zdůvodnění je v `Docs/MAP_DESIGN.md`.

Pořadí pravdy při rozporu:

1. **Světlo, obloha, mraky, expozice:** `Web/src/data/environment.json` (jediný zdroj). Mlha mapy je výjimka zapsaná jako
   rozhodnutí **D9** v `Docs/ARCHITECTURE.md` (hodnoty v oddílu 5.4). Tento dokument hodnoty jen opakuje a vysvětluje.
2. **Geometrie, rozměry, identifikátory materiálů:** `layout.json` a `buildings.json`. Každý řetězec `material`, `finish_*`,
   `floor_material`, `surface` v datech patří do jedné materiálové rodiny z oddílu 3. Nový identifikátor se smí přidat jen
   s přiřazením k rodině.
3. **Paleta, rozsahy PBR, styl, opotřebení, nápisy:** tento dokument.

---

## 1. Vizuální identita

**Kalné Hamry** jsou fiktivní česká obec v údolí Kalného potoka. Stojí na soutoku tří údolí ve tvaru Y. Hamr zde stál od
18. století, dnes je z něj zámečnická dílna (ref. 04). Dále tu je cihlový sklad stavebnin z doby JZD se zeleno-šedou
vlnitou střechou (ref. 01, 03), dvoupodlažní dům mistra s červenou taškovou střechou v zahradě obehnané zdí (ref. 01),
kaple se zvoničkou v klínu silnic, hostinec, hasičská zbrojnice, garáže, sloupová trafostanice, zděné kůlny (ref. 05)
a několik chalup. Obec byla před několika dny evakuována a armáda údolí uzavřela kordonem.

Situace: **10. září 2026, 15:05 SELČ**, teplé odpoledne na konci léta **těsně po přeháňce**: asfalt, beton a kovové plochy
jsou ještě mokré, v prohlubních silnice a dvorů stojí kaluže (ref. 02, 03), tráva a omítky už oschly. Slunce svítí
z jihozápadu, na obloze jsou asi 3/8 kupovité oblačnosti. Nic neprší a nic se nehýbe rychleji než listí. (Reference ukazují
nižší pozdní slunce; světlo zůstává z `environment.json`, viz `REFERENCE_DECISIONS.md` R-10.)

Tři slova pro celou mapu: **užívané, klidné, čitelné.**

- **Užívané:** místo působí, jako by ho lidé opustili včera. Na šňůře visí prádlo, u domu stojí kolečko, v dílně je traktor
  na špalcích. Pneumatiky zanechaly stopy v blátě. Nejde o válečnou ruinu: budovy jsou celé, poškození je jen lokální
  (rozbité okno, oprýskaná omítka, vypálený autobus jako zátaras).
- **Klidné:** barvy jsou přírodní, nasycení střední, kontrast odpovídá slunečnému dni. Filmovost dává jen tone mapping,
  mírně teplé světlo a vzdušná perspektiva, nikdy barevný filtr.
- **Čitelné:** hráč musí za 0,5 s rozeznat postavu od pozadí, kryt od zakrytí a průchozí dveře od zamčených. Proto platí
  barevná rezerva v oddílu 2.3 a pravidla pro zavřené budovy v oddílu 6.5.

Měřítko: vše se odvozuje od dospělého člověka 1,80 m (kapsle r 0,35 m). Dveře mají světlou výšku ≥ 2,05 m, kliky jsou ve
výšce 1,05 m, parapety oken obytných místností 0,85–0,95 m, zábradlí 1,00 m, schodišťový stupeň 0,16–0,19 m. Rekvizity
(auta, palety, sudy) mají skutečné rozměry z `prop_catalog`. **Nic nesmí levitovat ani se náhodně protínat.** Kontrolu
výšky na terénu dělá `Tools/level/check_layout.py` (L04), vizuální kontrolu provádí tvůrce assetu (oddíl 9).

---

## 2. Paleta (sRGB hex)

Hodnoty jsou **střední base colour** povrchu bez osvětlení. Variace textury smí jít ±8 % v jasu a ±4 % v odstínu kolem
střední hodnoty, rozsahy pro celou rodinu jsou v oddílu 3.

### 2.1 Krajina

| Povrch | Hex | Poznámka |
| --- | --- | --- |
| louka na slunci | `#8E9A55` | koncem léta, s příměsí suché trávy |
| louka ve stínu / vlhká u potoka | `#5F6B3B` | sytější, tmavší |
| suchá tráva, strniště, posečené pruhy | `#B5A66E` | na výsušných svazích (jižní expozice) |
| sečený trávník zahrad | `#7A8C47` | jen zahrada domu a okolí kapličky |
| zemina polní cesty, vyjeté koleje | `#7A6448` | |
| bláto mokré (příkopy, koleje, u brodu) | `#4B3F31` | roughness nízká, viz 3.1 |
| štěrk (dvory, cesta C uprostřed) | `#9C978C` | drcená droba, šedozelený nádech |
| lesní hrabanka (bukový les) | `#5A4A36` | |
| kamenitý břeh a dno potoka | `#6F6D63` | droba |
| voda potoka (v tůňkách / na mělčině) | `#3F4A3C` / `#6B6A55` | mělká, hnědozelená, bez pěny |
| listí (lípa, javor, buk) v plném světle | `#5E7A36` | na přechodu k podzimu |
| podzimní akcent (bříza, lípa, max. 5 % korun) | `#B8923A` | jen jednotlivé větve, žádné celé žluté stromy |
| smrk – jehličí (R11) / kůra | `#2F3D26` / `#5E5448` | tmavší a studenější než listnáče; les na svazích a u hranice |
| bříza – kůra (R10, R15) | `#D8D4C8`, trhliny `#2E2B28` | bílá kůra s černými trhlinami u paty |
| luční květy (R17): řebříček, heřmánek | `#E8E4D6` / `#F2E9A0` | jen drobné akcenty v trávě |
| mokrý štěrk a beton dvorů (ref. 02) | `#7E6E62` | tmavší o 15 % než suché, kaluže v prohlubních |
| vzdálené kopce (vzdušná perspektiva, 1–2 km) | `#7D8C86` | výsledný tón po mlze, nikoli barva textury |

### 2.2 Stavby a infrastruktura

| Materiál | Hex | Kde |
| --- | --- | --- |
| **zvětralá vápenná omítka přes cihlu** (krémová, opadaná 20–40 %) | `#D9CBB3` (lit `#E3C4A4`–`#F9E8D2`) | dílna, kůlny R05, kaple, chalupy; odhalená cihla v ostrovech na soklu, rozích a pod okapem |
| omítka krémová hladší (dům) | `#D6C8A8` | dům mistra, zahradní zeď (šedší ve stínu `#756B5F`) |
| cementová šedá omítka (sokly) | `#9A968D` | |
| **cihla režná** (odhalená v omítce, zdivo skladu) | `#A0573D`; sklad sazemi tmavší `#7A4E3C` | komíny `#8A4A38`; spára malta `#A59C8C` |
| omítnuté pilastry a římsa skladu | `#CFC3AC` | ref. 03 |
| droba – lomový kámen (opěrná zeď dílny, kamenná chalupa) | `#6F6D63` | šedozelená |
| **beton** (rampa, zídky, lávky, sokly kůlen, opěrné zdi) | `#A5A19A` / zvětralý s mechem `#8C877E` | ref. 02: lávka `#979294` |
| **tmavý vlnitý plech** (dílna, kůlny, zastávka) | `#55524F` (lit `#52535A`) | rezavé skvrny a stékání `#7A4B2E` na 10–25 % |
| **zelený vlnitý plech** (sklad) | `#687468` (ve stínu `#5F6565`) | vybledlý, na hřebeni a u okapu rez |
| **pálená drážková taška** (dům, křídlo) | `#A5553A` (ve stínu `#805848`) | mech a lišejník na severní straně |
| **rezavá ocelová vrata** (dílna) | `#8E5038` (lit `#B6674C`) | rám a výplň z plechu, nátěr zbyl ve skvrnách `#5D6B77` |
| šedá ocel posuvných vrat a dveří kůlen | `#56616A` (ref. 03 `#3F494F`, ref. 05 `#9C948E`) | |
| ocel natřená modrošedá (zárubně, zábradlí) | `#5D6B77` | |
| pozinkovaný plech (okapy, svody, rošty) | `#A7ABAA` | kov, viz 3.3 |
| rez | `#7A4B2E` | hrany, spoje, trubky zábradlí R16 |
| ocelová dělená okna (dílna, sklad) | rám `#3A3A3C`, sklo špinavé | |
| dřevo natřené krémové / bílé (okna a dveře domu) | `#D6CCAE` / `#E6E2D8` | |
| šedé zvětralé dřevo (zastávka R06, ploty, kůlny) | `#8C8579` | tmavší u země `#5A4231` |
| olejový sokl v dílně (zelená „olejová“ barva do 1,5 m) | `#5E7358` | nad ním bílá vápenná malba `#E4E0D4` |
| **mokrý asfalt** / suchý okraj / záplata | `#44474C` / `#56565A` / `#3E3E40` | silnice A a B, kaluže jako dekály (roughness 0,05–0,15) |
| vodorovné značení (bílé, ojeté) | `#D9D6CC` | středová přerušovaná a okrajové čáry |
| žulové kostky návsi, obrubníky | `#8A8680` | |

### 2.3 Herní a vojenské barvy (rezervované)

| Účel | Hex | Pravidlo |
| --- | --- | --- |
| tým Alfa | `#3D8BFD` (tmavá `#1F4F99`) | z `Web/src/data/teams.json`; jen týmová plachta nákladního auta, páska na rukávu, HUD |
| tým Bravo | `#E5533D` (tmavá `#8A2A1C`) | totéž |
| tým Charlie | `#F2C230` (tmavá `#8F6F12`) | totéž |
| aktivní zóna: signální kouř | `#7E57C2` | fialový; nepatří žádnému týmu |
| aktivní zóna: čára na zemi | `#F2F0EA` | bílá, 0,12 m, jako vodorovné dopravní značení |
| bedna s převaděčem | `#4F5A3A` | olivová, bez znaků reálné armády |
| kontejnery (clony spawnů) | `#5C5F3E` / `#7B4C31` | olivový nátěr, rezavé plochy |
| HESCO (geotextilie / pletivo) | `#BDB08F` / `#6E6E68` | |
| betonové zátarasy | `#B3AEA3` | |
| výstražné cedule (červená / žlutá výstražná) | `#C0392B` / `#E8B21A` | jen na ceduli, nikdy na velkých plochách |

**Pravidlo rezervy:** čistě modrá, červená a žlutá o sytosti nad 60 % (HSV) se na velkých plochách prostředí nesmějí
objevit. Jde o fasády, auta, kontejnery a plachty. Výjimky jsou drobné (dopravní značky, výstražné cedule, poštovní
schránka) a smějí zabírat nejvýš 0,5 m². Týmovou barvu tak hráč nikdy nezamění s kulisou. Proto také zóna používá
fialovou a bílou, nikoli žlutou.

Uniformy všech tří týmů mají stejný olivový maskovací základ. Týmy se liší jen barevnými prvky z tabulky, čímž si nekonkurují
s prostředím.

---

## 3. Materiály a rozsahy PBR

Workflow: **metal/roughness**, glTF 2.0 (three.js) a UE5 Substrate/Default Lit se stejnými vstupy.

- **Base colour** je v sRGB, **ORM** (R = occlusion, G = roughness, B = metallic, jako v glTF) je lineární.
- **Normálové mapy** se tvoří v konvenci OpenGL (+Y, jako glTF/three.js). Při importu do UE5 se zelený kanál převrátí
  (`Flip Green Channel`).
- **Base colour nesmí obsahovat zapečené světlo, stíny ani odlesky.** Okluze patří jen do kanálu R v ORM. Kontrola: textura
  vypadá ploše i při otočení o 180°.
- Base colour musí být fyzikálně věrohodný. Nekovy mají sRGB 30–240 (lineárně cca 0,012–0,87), žádný povrch není čistě
  černý ani čistě bílý. Kovy (metallic = 1) mají base colour = odrazivost, sRGB 150–235.
- Metallic je **0 nebo 1**. Mezihodnoty jsou jen na přechodech (rez na oceli, prach na kovu) a vznikají maskou, ne
  globálním nastavením.
- **Lesk se nesdílí.** Kov, omítka, látka, kůže, bláto a polymer mají každý jiný rozsah roughness (zadání §8). Tabulky níže
  jsou nastavené tak, aby se střední hodnoty sousedních rodin lišily nejméně o 0,10.

Hodnoty base colour jsou uvedené jako **rozsah jasu v sRGB (0–255)** a typický hex. Roughness a metallic jsou v rozsahu
0–1.

### 3.1 Terén a venkovní povrchy

| Rodina (identifikátory v datech) | Base colour sRGB | Roughness | Metallic | Poznámka |
| --- | --- | --- | --- | --- |
| tráva, louka (`grass`, `mud_grass`) | 70–150, `#8E9A55` | 0,85–0,95 | 0 | mapa splatu + instancovaná tráva do 40 m |
| zemina, polní cesta (`dirt`, `dirt_track_gravel_centre`) | 85–130, `#7A6448` | 0,85–0,98 | 0 | vyjeté koleje 0,08 m jako normála + výška splatu |
| bláto mokré (`mud`) | 45–80, `#4B3F31` | 0,35–0,60 | 0 | jediný „lesklý“ přírodní povrch; lokálně louže 0,05–0,15 |
| štěrk (`gravel`) | 120–165, `#9C978C` | 0,90–1,00 | 0 | normála s výraznými zrny, žádné opakování menší než 4 m |
| lesní hrabanka (`forest_floor`) | 60–100, `#5A4A36` | 0,90–1,00 | 0 | jen za hranicí a na okrajích |
| asfalt (`asphalt`) | 55–95, `#4E4E4F` | suchý 0,80–0,92 (ojetý pruh 0,72–0,80) | 0 | trhliny a záplaty jako dekály |
| **mokrý asfalt** (stav mapy, ref. 02/03) | base colour −15 % jasu, `#44474C` | 0,25–0,40; kaluže 0,03–0,10 (dekály s maskou výšky, jen v prohlubních a u obrubníků) | 0 | odlesk oblohy a slunce, žádná pěna; beton a kovy ve venkovních plochách o 0,15 hladší |
| beton, betonové desky (`concrete`, `concrete_slabs`, `concrete_broom`) | 130–185, `#A9A59C` | 0,75–0,90 | 0 | povrch „koště“ = jemné rýhy v normále |
| kostky, dlažba (`paving`, `paving_granite_setts`) | 110–150, `#8A8680` | 0,70–0,85 | 0 | spáry tmavší, s mechem na okrajích |
| kámen, droba, pískovec (`stone`, `stone_rubble_*`, `stone_lined_dry`) | 90–185 | 0,70–0,90 | 0 | pískovec světlejší a drsnější než droba |
| voda (`shallow_brook_water`) | dno viditelné, barva absorpce `#3F4A3C` | 0,02–0,08 | 0 | hloubka 0,25 m; vlnky jen z normálové mapy, bez pěny |

### 3.2 Stavební materiály

| Rodina | Base colour sRGB | Roughness | Metallic | Poznámka |
| --- | --- | --- | --- | --- |
| omítky vnější (`render_lime_*`, `render_cement_*`) | 140–225 | 0,85–0,95 | 0 | makrovariace a stékání pod parapety, viz oddíl 8 |
| omítky a malby vnitřní (`plaster_*`) | 170–230 | 0,80–0,92 | 0 | olejový sokl dílny 0,45–0,60 |
| cihla režná (`brick_*`, viditelné zdivo) | 90–150 | 0,75–0,90 | 0 | spára 10 mm, malta `#A59C8C` |
| beton konstrukční (`reinforced_concrete_*`, `precast_*`) | 130–180 | 0,70–0,88 | 0 | stopy bednění na viditelných plochách |
| terrazzo (`terrazzo_*`) | 150–200 | 0,30–0,45 | 0 | leštěné schody a chodby domu, opotřebené dráhy 0,50 |
| keramická dlažba a obklady (`ceramic_tiles_*`, `tiles_*`) | 120–235 | 0,15–0,35 | 0 | spáry drsnější (0,85) |
| vinyl, linoleum (`vinyl_tiles_*`) | 130–200 | 0,40–0,55 | 0 | |
| dřevo surové a zvětralé (prkna, kůlny, `timber_boards`) | 70–150 | 0,70–0,90 | 0 | šedne na povětrnostní straně |
| dřevo natřené (`timber_*_paint*`) | podle nátěru | 0,45–0,65 (oprýskané místo 0,85) | 0 | nátěr je dielektrikum, nikdy metallic |
| parkety (`timber_parquet`) | 100–160 | 0,40–0,60 | 0 | vyšlapaná dráha matnější |
| pálená taška (`clay_tile_*`) | 90–150 | 0,70–0,85 | 0 | lišejník a mech na severní straně |
| fibrocement vlnitý (`fibre_cement_*`) | 120–160 | 0,80–0,92 | 0 | jen vedlejší budovy (chalupy B) |
| **vlnitý plech tmavý** (`corrugated_sheet_dark_grey_weathered`: dílna, kůlny R05, zastávka) | 70–100, `#55524F` | nátěr 0,55–0,70, rez 0,80–0,95 | 0 (holý plech na hranách 1) | vlna 76 mm jako geometrie na LOD0, rezavé skvrny a stékání od šroubů |
| **vlnitý plech zelený** (`corrugated_steel_green_weathered`: sklad) | 90–125, `#687468` | 0,50–0,65 | 0 | vybledlý na jižní ploše, lišejník u okapu |
| **pálená drážková taška** (`clay_tile_interlocking_red_orange_weathered`: dům) | 110–170, `#A5553A` | 0,70–0,85 | 0 | mech na severní ploše, tmavší hřebenáče |
| sklo okenní | tónování `#9AA7A6`, α 0,15–0,25 | 0,03–0,10 | 0 | odraz oblohy, ve v1 nerozbitné; špinavé sklo až 0,30 |
| polykarbonát (světlíky skladu) | 190–220, průsvitný | 0,25–0,40 | 0 | propouští světlo, neprůhledný pro výhled |

### 3.3 Kovy a nátěry kovů

| Rodina | Base colour sRGB | Roughness | Metallic | Poznámka |
| --- | --- | --- | --- | --- |
| ocel natřená (`steel_*_paint*`, `steel_blue_grey`, posuvná vrata, zárubně) | podle nátěru 70–150 | 0,40–0,65 | **0** | nátěr je nekov |
| odřený nátěr, holá ocel na hranách | 150–190 | 0,35–0,55 | 1 | maska jen na hranách, klikách, schodnicích |
| pozink (`galvanised_*`, okapy, svody, rošty) | 165–200 | 0,35–0,55 | 1 | skvrnitá variace (spangle) jen v roughness |
| rez (`rust` maska) | 70–120, `#7A4B2E` | 0,75–0,95 | 0 | rez je oxid, tedy nekov |
| hliník (rámy dveří kanceláře skladu, `hpl_grey` je laminát, ne kov) | 190–225 | 0,30–0,50 | 1 | |
| litina (vpusti, kanálové poklopy) | 60–90 | 0,55–0,75 | 1 | na pochozích místech lesklejší (0,40) |

### 3.4 Rekvizity, látky a polymery

| Rodina | Base colour sRGB | Roughness | Metallic | Poznámka |
| --- | --- | --- | --- | --- |
| látka, plachty, pytle (`big_bags`, pytle cementu, čalounění) | 40–200 | 0,88–1,00 | 0 | nejdrsnější rodina |
| kůže (sedačky vozidel, řemeny) | 40–120 | 0,50–0,70 | 0 | |
| polymer tvrdý (IBC nádrže, přepravky, sudy PE) | 60–220 | 0,35–0,55 | 0 | IBC nádrž je průsvitná bílá |
| guma (pneumatiky) | 25–45 | 0,80–0,92 | 0 | |
| lakovaná karoserie (civilní auta) | tlumené barvy 60–170 | 0,25–0,45 (ojetá 0,55) | 0 | sytost ≤ 45 %, viz pravidlo rezervy |
| vyhořelé vraky (`*_wreck`) | 30–90 | 0,75–0,95 | 0 (ocel na hranách 1) | saze a rez, bez skel |
| HESCO geotextilie a pletivo | 150–200 / 90–120 | 0,90 / 0,45 | 0 / 1 | pletivo jako alfa maska přes geotextilii |
| kontejnery ISO (nátěr) | 70–120 | 0,45–0,65 | 0 | vlnitá stěna je geometrie, ne normála |

### 3.5 Textury a hustota detailu

- Hustota texelů: budovy a interiéry **512 px/m** (trim sheety 2k), rekvizity **512–1024 px/m** (atlas 1k), terén **256
  px/m** pro detailní vrstvu a k tomu makrovariace 1 px/m přes celou mapu.
- Terén: splat se 4 vrstvami (tráva, zemina, štěrk, bláto) a detailní normálou. Dlažbu, asfalt a beton tvoří geometrie
  cest a pásů s vlastním materiálem. Rozdíl hustoty texelů mezi sousedními objekty smí být nejvýš 2×.
- Opakování: žádný motiv se nesmí opakovat v rastru menším než 4 m. Dlaždicové textury se rozbíjejí makrovariací
  a dekály (skvrny, stékání, trhliny).
- Formát (rozhodnutí D3, bez WASM): předkomprimované **DDS BC1/BC3/BC5** s mipmapami, záložní JPEG/PNG. **KTX2 ani
  Basis se nepoužívají.** Rozpočet VRAM je 700 MB na textury a geometrii.

---

## 4. Architektura

Obecně platí: každá hlavní budova má čitelný účel a všechny tyto prvky: základ a sokl, skutečnou tloušťku zdí, okna osazená
do hloubky ostění, dveřní rám a práh, střechu s přesahem, okapy se svody zakončenými vpustí nebo rozstřikem a napojení na
terén. Konstrukce se generuje **bez booleovských operací**: zeď je kvádr rozdělený na pilíře, parapetní a nadpražní bloky
(`construction_boxes` v `buildings.json`). Rámy, parapety, ostění a lemování jsou instancované moduly.

Společné detaily:

- **Okna:** rám je osazen 0,12 m za líc fasády (`reveal_depth` 0,12 v `buildings.json`, hloubka ostění musí být vidět).
  Vnější parapet přečnívá 0,04 m s okapničkou (`sill_overhang`). Pod parapety jsou jemné stopy stékání. Okna dílny a skladu
  jsou ocelová členěná (ref. 03, 04), v domě dřevěná zdvojená okna bílá nebo krémová. Okna ve štítech (nad korunou zdi)
  mají vlastní konstrukční polygony štítu (`walls[].gable`).
- **Dveře:** světlá šířka ≥ 1,10 m a světlá výška ≥ 2,05 m (projektové pravidlo pro navmesh, zadání požaduje 0,90). Zárubeň
  má 0,05 m, křídlo 0,05 m a výrazný práh. Klika je ve výšce 1,05 m. Průchozí dveře stojí otevřené v klidové poloze
  (`open_deg`) a jejich křídlo se musí vejít k zarážce. Zavřené dveře neprůchozích budov popisuje oddíl 6.5.
- **Střechy:** přesah okapu podle dat (`overhang_eave`: hala dílny 0,45, přístavek 0,35, kůlna 0,30, sklad 0,40, přístřešek
  rampy 0,35, dům 0,60, křídlo 0,45), u štítu `overhang_verge`. Okapy jsou půlkruhové pozinkované (125 mm) a **visí 0,03 m pod
  odkapní hranou** střechy (`gutters[].drip_edge_z` = `eave_z` − přesah × tg sklonu, kontroluje `check_layout.py` B16); svody
  100 mm začínají v žlabu a ústí do rozstřikové dlaždice, do vpusti nebo do chrliče v opěrné zdi (`downpipes[].outlet`). Voda musí mít vždy
  kam odtéct (ENV-01): dvory mají spád 1 % k vpustem nebo k potoku, opěrné zdi mají odvodňovací otvory po 2 m.
- **Napojení na terén:** terén kolem budovy leží o jeden stupeň (0,17 m) pod podlahou. Každé venkovní dveře končí na
  rovině, podestě, schodu nebo nakládací rampě. Kontroluje to `check_layout.py` (L03).

### 4.1 Dílna (bývalý hamr), `B_DILNA` – podle ref. 04 a 02

- Hamr z 18. století byl kolem roku 1924 přestavěn na cihlovou zámečnickou dílnu (Kalina a syn) a od 60. let sloužil jako
  opravna zemědělských strojů. **Jednopodlažní, půdorys L:** hala 14,5 × 10,0 m (okap 4,60, sedlová střecha 30°, hřeben
  7,49), ustoupený přístavek 6,5 × 7,8 m (okap 3,00, 30°, výdejna + šatna se stropem z prken 2,85) a pultová kůlna
  3,5 × 5,0 m (kompresorovna). Hala je bez stropu, vazné trámy krovu 4,20 m.
- Zdivo cihelné 450 mm (kůlna 300 mm), **zvětralá vápenná omítka přes cihlu**, opadaná v ostrovech (sokl, rohy, pod okapy,
  kolem vrat). Kamenný sokl 0,47 m viditelný. **Tmavý vlnitý plech** na všech třech střechách, světlík ve střeše haly.
- Průčelí: okno, **dvoukřídlá rezavá ocelová vrata 3,40 × 3,40** (otevřená, křídla na 100°), větrací štěrbina, druhá vrata
  2,60 × 3,40, okno; nad vraty dvě smaltované kuželové lampy; 4 pozinkované svody. Dva cihlové komíny s krycí deskou
  (kovárna a kamna uvnitř). Na štítu vybledlý nápis „KALINA A SYN – ZÁMEČNICTVÍ“.
- Okna ocelová dělená (tabulky ~0,25 × 0,27), rám 0,12 m za lícem, parapet přečnívá 0,04 m (`reveal_depth`,
  `sill_overhang` v datech). Uvnitř zelený olejový sokl do 1,5 m a bílá vápenná malba.

### 4.2 Menší sklad (stavebniny), `B_SKLAD` – podle ref. 01 a 03

- Sklad hnojiv JZD z roku 1976, dnes **Stavebniny Kalina**. Dlouhá **hala z režných cihel 25,0 × 12,5 m** (zdivo 450 mm)
  s **omítnutými pilastry** 0,6 m po 5 m a římsou, okap 5,50, sedlová střecha 20° z **zeleného vlnitého plechu** s větracím
  nástavcem na hřebeni, štíty s okny.
- Průčelí k dvoru: **posuvná ocelová vrata 3,6 × 4,0** (jedna otevřená, křídlo zaparkované přes plnou zeď; jedna zavřená
  s visacím zámkem), velká ocelová okna 2,4 × 2,2 (parapet 1,5), dveře; vzadu další otevřená posuvná vrata. Cihly sazemi
  tmavší, pilastry a římsa světlá omítka.
- Podél průčelí betonová **nakládací rampa 1,10 m** (ocelová hrana, pryžové nárazníky) s pultovým přístřeškem na sloupcích
  (sloupky stojí mimo osy schodů), dva schody a nájezd 1:6. Plošina skladu je zaříznutá do svahu a drží ji betonové opěrné
  zdi s ocelovým zábradlím nahoře.
- Kancelář v rohu haly má strop (`SK_OFFICE_CEILING`, nepochozí) a kamna s komínem.

### 4.3 Obytný dům (dům mistra), `B_DUM` – podle ref. 01

- Zděný **dvoupodlažní dům** z roku 1934, 11,0 × 9,5 m, **valbová střecha z červených pálených tašek** 40° (okap 6,10,
  hřeben 10,09), dva vikýře do zahrady, komín; na západě **přízemní křídlo** 4,5 × 6,0 m s valbou 35° (kuchyně s kamny).
  Krémová hladší vápenná omítka, šambrány v lomené bílé, sokl cementový šedý 0,54 m.
- Dům stojí na terase nad návsí v **zahradě obehnané zdí**: terasovou zeď drží lomový kámen s omítnutou zahradní zdí 1,00 m
  nad terasou (celkem 3,10 m od návsi), boční a zadní zahradní zdi jsou omítnuté 1,8 m s ocelovými brankami. Ve zdi je
  zapuštěná garáž (jen čelo) a zahradní schody. Balkon s plným parapetem je nad zadním dvorem.
- Interiér: terrazzo v chodbách, dlažba v kuchyni a koupelně, parkety v pokojích, bílé dveře.

### 4.4 Vedlejší budovy (vždy `"enterable": false`)

- **Kůlna R05** (ref. 05) se opakuje 5×: zděná 3,8 × 3,2 m, pultová střecha z rezavého plechu (nízký okap 2,5 u dveří,
  vzadu 3,4), omítka opadaná na cihlu, betonový sokl 0,30 m, šedé ocelové dveře (zamčené), zamřížované okénko, žaluziová
  mřížka, lampa v kleci, žlab na nízké straně.
- **Kaple se zvoničkou** 4,6 × 6,8 m (okap 3,6, hřeben 5,9, zvonička 1,6 m do 8,2 m s křížem), krémová omítka, obloukové
  dveře a výklenek se sochou; kolem nízká omítnutá betonová zídka 1,1 m.
- **Zastávka R06** (dřevěná, 3,6 × 2,0 × 2,9 m, jediná přístupná – bez interiéru), **sloupová trafostanice** (transformátor
  na plošině mezi dvěma dřevěnými sloupy, oplocená pletivem R14).
- Hostinec U Hamru (zabedněný), hasičská zbrojnice se sušicí věží, řadové garáže, stánek s roletami, dřevník, seník,
  stodola, **otevřená kolna na stroje** (čelo zaplněné stohem balíků, kolize = celý půdorys), kancelář štěrkovny a čtyři
  uzavřené chalupy (A okrová/taška, B šedá omítka/eternit, C bílá/červená taška se zabedněnými okny, D kamenná).
- Každá stojí na srovnané plošině se soklem 0,30 m (patka 0,15 m pod terénem; kde silnice zasahuje do plošiny, sokl je
  stupňovitý) – `secondary_buildings[].plinth`. Tvar, výšky a sklony jsou v `layout.json`.

---

## 5. Osvětlení a atmosféra

Hodnoty jsou převzaté z `Web/src/data/environment.json`. Při změně tohoto souboru platí nová hodnota a tento oddíl se
aktualizuje.

### 5.1 Slunce

| Parametr | Hodnota |
| --- | --- |
| azimut (kompas, od severu po směru hodin) | **222°** (jihozápad) |
| výška | **38°** |
| směr ke slunci ve světě mapy (x, y, z) | (−0,527, −0,586, 0,616) |
| barva / intenzita (three.js) | `#fff1dc` / 5,0 |
| stíny | mapa 2048, rozsah 28 m, radius 1,5 texelu (polostín ~8 cm), bias 0,0045 m, normal bias 0,025 |
| odpovídající čas | 10. 9. 2026 15:05 SELČ, 49,90° s. š. 15,10° v. d. (fiktivní místo), odchylka do 0,3° |
| UE5 | Directional Light jako Atmosphere Sun, 75 000 lx, úhel zdroje 0,53° |

Důsledky pro čitelnost: stíny padají k severovýchodu. Průčelí skladu (západ) a zahrada domu (jih) jsou na slunci, dvůr
dílny (průčelí na JV) je v bočním světle a severní průčelí domu je ve stínu. Každá zóna tak má jiný světelný charakter.
Stín nesmí být černý. Minimum dává odražené světlo z oblohy a ze země (oddíl 5.3).

### 5.2 Obloha a mraky

- Model: three.js Sky (Preetham) s vrstvou mraků `Web/src/engine/clouds.js`. V UE5 odpovídá SkyAtmosphere + Volumetric
  Cloud.
- Sky: turbidity 3,2, rayleigh 1,15, mieCoefficient 0,004, mieDirectionalG 0,78.
- Mraky: cloudCoverage 0,4 (asi 3/8 kupovité oblačnosti pěkného počasí), cloudDensity 0,8, cloudScale 0,0007, cloudElevation
  0,55, vrstva ve výšce 1800 m, cloudDetail 1,0, cloudSunAbsorption 2,2.
- **cloudSpeed = 0:** mraky stojí, takže časově neblikají (ENV-04). Mraky jsou nasvícené ze stejného směru jako slunce
  a nesmějí působit jako ploché skvrny ani jako textura s nízkým rozlišením na kouli.

### 5.3 Okolní světlo a expozice

- Hemisféra: obloha `#bcd4ee`, zem `#6f6a5e`, intenzita 0,08.
- Světlo z prostředí (IBL): environmentIntensity 0,3, environmentSkySaturation 0,35, odražená zem `#75766e`.
- Zapečené nepřímé světlo úrovně: 32 paprsků na vrchol, ambientFloor 0,2 v uzavřených prostorech.
- Expozice **0,55** (ACES Filmic). Adaptace oka při vstupu dovnitř: nejvýš ×2,0, zesvětlení 1,2/s, ztmavení při výstupu
  ven 3,0/s. V UE5 platí manuální EV100 14,0 venku a auto exposure 11,5–14,5 pro interiéry.
- Přechod ven/dovnitř (ENV-04) se testuje u vrat dílny, u dveří kanceláře skladu a u vchodu do domu (testovací body
  v `MAP_DESIGN.md`).

### 5.4 Mlha (rozhodnutí D9)

| Parametr | `environment.json` (zkušební střelnice) | **Mapa Kalné Hamry (D9)** |
| --- | --- | --- |
| barva | `#c3cfd9` | `#c3cfd9` |
| hustota (FogExp2) | 0,0045 | **0,0012** |
| výšková hustota | 0,0035 | **0,0006** |
| výškový pokles | 0,12 | **0,08** |
| základní výška | 0,0 | 0,0 |

Výsledek ve výšce očí: asi 3,6 % mlhy na 60 m, 10 % na 150 m (limit vnímání AI), 40 % na 600 m (bližší hřebeny) a více než
90 % za 1,4 km. Hodnoty střelnice by na 150 m vzaly 59 % kontrastu a smazaly by vzdálené kopce. **Mlha je jen vizuální.
Nesmí skrývat hranici mapy, LOD přechody bližší než 250 m ani slabinu viditelnosti, kterou má řešit geometrie.**

---

## 6. Vegetace

Uvnitř hrací plochy rostou **převážně listnaté dřeviny** (zadání §3). Reference R11 a 01–03 ukazují smrky na svazích a na
okraji mapy, proto: smrk a borovice tvoří les za hranicí a okrajový pás (≤ 12 m za měkkou hranicí), uvnitř hrací plochy
je jehličnanů **nejvýš 12 %** stromů a žádný nestojí blíž než 3 m od zóny nebo spawnu (`check_layout.py` G01). Živé ploty
uvnitř mapy jsou habrové nebo z ptačího zobu, nikdy z túje.

### 6.1 Stromy (`trees.species`, 1650 instancí)

| Id | Druh | Výška / poloměr koruny | Kde |
| --- | --- | --- | --- |
| `lipa_stara` | lípa velkolistá (*Tilia platyphyllos*), památná | 22 / 8,5 m | náves, u kapličky |
| `lipa` | lípa srdčitá (*Tilia cordata*) | 18 / 6,5 m | obec, stromořadí |
| `javor` | javor klen (*Acer pseudoplatanus*) | 17 / 5,5 m | obec, okraje lesa |
| `jasan` | jasan ztepilý (*Fraxinus excelsior*) | 18 / 5,0 m | vlhké svahy u potoka |
| `dub` | dub letní (*Quercus robur*) | 18 / 6,5 m | jižní lesní okraj, solitéry na mezích |
| `buk` | buk lesní (*Fagus sylvatica*) | 22 / 5,5 m | les na svazích (hlavní les kulis) |
| `habr` | habr obecný (*Carpinus betulus*) | 12 / 4,0 m | podrost okraje lesa, meze |
| `olse` | olše lepkavá (*Alnus glutinosa*) | 14 / 3,5 m | břehy Kalného potoka |
| `vrba` | vrba křehká (*Salix fragilis*) | 11 / 4,5 m | břehy, u jezu |
| `briza` | bříza bělokorá vzrostlá (*Betula pendula*, R15) | 16 / 3,5 m | solitéry u cest a návsi, u štěrkovny |
| `briza_mlada` | bříza mladá (R10) | 13 / 2,5 m | náletové skupiny, okraj lesa |
| `smrk` | smrk ztepilý (*Picea abies*, R11) | 22 / 3,5 m | les na svazích, okrajový pás, 2 u kaple, řada podél východní polní cesty |
| `borovice` | borovice lesní (*Pinus sylvestris*) | 20 / 3,5 m | les na svazích (ref. 01) |
| `jablon` | jabloň (stará odrůda) | 6,5 / 3,0 m | starý sad na SZ ostrohu, zahrady |
| `hruska` | hrušeň | 9 / 3,0 m | sad, alej u cesty C |
| `svestka` | švestka | 6 / 2,5 m | zahrady, alej u cesty C |
| `orech` | ořešák královský | 12 / 6,0 m | dvůr domu, u hostince |

Rozmístění podle vlhkosti a sklonu: olše a vrby rostou 5,2–6,8 m od osy potoka, sad na výsušném SZ ostrohu, buk a dub
v lese a jasany na vlhkých úpatích. Kmen je zapuštěný 0,10 m do terénu (kořenový náběh). Pravidla rozmístění jsou
v `layout.json` (`trees.placement_rules`, seed 20260926).

Stav: začátek září. Koruny jsou plně zelené, u bříz a lip je nejvýš 5 % zežloutlých větví. Na jabloních a švestkách jsou
plody a pod nimi pár spadaných. Louky jsou zčásti posečené a na svahu u statku leží balíky.

### 6.2 Keře, živé ploty, remízky

| Typ (`vegetation_blocks`, `fences_walls_hedges`) | Složení | Výška |
| --- | --- | --- |
| břehový pás keřů (`shrub_belt`) | líska 40 %, bez černý 25 %, trnka 20 %, mladá olše a vrba 15 % | 3,0 m |
| polní remízek (`shrub_copse`) | trnka, hloh, šípková růže, 1–3 stromy | 3,5 m |
| větrolam (`windbreak_belt`) | habr, javor babyka, líska | 4–6 m |
| mez s keři (`hedgerow_mixed`) | hloh, trnka, líska, šípek | 2,2–2,4 m |
| zahradní živý plot (`hedge_privet`, `hedge_hornbeam`) | ptačí zob, habr (stříhané) | 1,8 m |

**Keře, které nesou kontrolu výhledu, musejí být husté až k zemi:** jde o instancované karty kolem souvislého kolizního
jádra, mezera v listí je nejvýš 10 % a pod 1,8 m není žádná průhledná díra větší než 0,3 m. Keře blokují pohyb a výhled
hráče i AI, ale **nejsou krytem** (střely projdou). Bezpečnost spawnů na keřích nestojí, protože ji zajišťují pevné clony
(HESCO, kontejnery, budovy).

### 6.3 Podrost a tráva

Instancovaná tráva se zobrazuje do 40 m (3 typy, 2 LOD). U zdí a plotů roste ruderální lem (kopřiva, lopuch, pelyněk), na
okraji potoka orobinec a chrastice a v mokrých kolejích sítina. Tráva nesmí růst přes cesty, dlažbu ani uvnitř budov a nesmí
zakrývat postavu ležící na zemi víc než do 0,3 m.

### 6.4 Rekvizity a vegetace z druhé sady referencí (R06–R17) – kolize, průstřelnost, výhled

| Ref. | Objekt | Data | Pohyb | Střela | Výhled |
| --- | --- | --- | --- | --- | --- |
| R06 | dřevěná čekárna 3,6 × 2,0 × 2,9 m, šedé smrkové dřevo, tmavý plech, granitové patky | `S_ZASTAVKA` (`bus_shelter_timber`) | blokuje stěny | dřevo **průstřelné** | laťová zadní stěna zakrývá |
| R07 | dřevěné sloupy vedení 8,5 m, izolátory, lampa se smaltovým kuželem, žluto-černé pruhy u paty | `utility_lines.poles/spans` | sloup r 0,14 m | blokuje | neblokuje |
| R08 | laťové bedny, europalety, stohy palet | `crate_stack_mixed`, `euro_pallet_stack_4`, `timber_stack_on_pallets` | blokuje | **průstřelné** (nízký kryt jen proti výhledu) | nízké – zakrývá v podřepu |
| R09 | trsy trávy 0,4 / 1,0 / 0,5 m | `ground_cover.types` | ne | ne | ne (kosmetické) |
| R10–R12, R15 | bříza mladá / vzrostlá, smrk, lípa, habr | `trees.species` | kmen | kmen | koruna nad 1,8 m |
| R13 | keře 0,8 / 1,3 / 2,0 m | `vegetation_blocks`, `ground_cover.shrub_*` | husté bloky ano | **ne – keř kulku nezastaví** | zakrývá |
| R14 | pletivo 1,5 m na betonové podezdívce 0,35 m, branka 1,0 m | `chain_link_on_plinth_1p5m` | blokuje | pletivo ne, podezdívka ano (0,35 m) | **průhledné** |
| R16 | betonové sloupky 0,25 × 0,25 × 1,0 m s dvěma rezavými trubkami | `BR_MAIN.railing`, `F_RAIL_NAVES` | blokuje | ne | neblokuje |
| R17 | řebříček, heřmánek, luční směs | `ground_cover` | ne | ne | ne |

Hustoty a pravidla rozmístění (vlhkost, sklon, okraje cest a zdí, nikdy na cestách a v zónách vyšší než 0,5 m) jsou
v `layout.json` → `ground_cover`; vojenský nákladní vůz, VZV, sudy a palety jsou statické rekvizity (`prop_catalog`).
Rekvizity na svahu mají `ground_fit` (naklopení `tilt`, přizpůsobení `conform`, svislá patka `upright_footing`).

### 6.5 Zavřené budovy a čitelnost průchodnosti

- Neprůchozí budova se musí **číst jako zavřená na první pohled**. Používá se zavřená okenice, zabedněné okno (OSB,
  zvětralé), visací zámek s řetězem, rezavá rolovací vrata, zatlučené dveře nebo cedule „ZAVŘENO“. Konkrétní řešení každé
  budovy určuje `reads_closed_by` v `layout.json`.
- **Žádné falešné dveře:** dveře, které vypadají průchozí (pootevřené, s tmavou mezerou, s osvětleným interiérem), se
  smějí objevit jen na průchozích budovách. Okna zavřených budov mají za sklem tmavou záclonu nebo desku, nikdy černou
  díru ani prázdný interiér.
- Průchozí dveře jsou naopak otevřené a v otvoru je vidět světlo interiéru.

---

## 7. Nápisy a značení (vše fiktivní)

Používají se jen **fiktivní** místní názvy a firmy (`check_layout.py` C01 hlídá seznam skutečných názvů z okolí). Nesmí se objevit reálné značky, loga, SPZ ani insignie skutečné armády.
Písmo dopravních značek je bezpatkové technické (volně licencované písmo DIN-like). Starší nápisy jsou ručně malované
patkovým písmem, vybledlé.

| Nápis | Kde |
| --- | --- |
| **Kalné Hamry** | tabule začátku obce na silnicích A a B (bílá s černým lemem) |
| **Nové Kalno 2 km** | směrovka na silnici A za zátarasem Alfy |
| **Štěrkovna Kalný Vrch – vstup zakázán** | brána štěrkovny za spawnem Bravo |
| **Hostinec U Hamru** | štít hostince, pod ním cedule „ZAVŘENO“ a vybledlá reklama na limonádu bez značky |
| **Stavebniny Kalina** | štít skladu nad rampou, menší cedule „Otevírací doba Po–Pá 7–16“ |
| **JZD Kalné Hamry – sklad hnojiv 1976** | vybledlý malovaný nápis na cihlovém štítu skladu |
| **Kalina a syn – zámečnictví** | vybledlý nápis na průčelí dílny nad vraty (přestavba 1924) |
| **SDH Kalné Hamry – Hasičská zbrojnice** | zbrojnice |
| **Kalné Hamry, náves** | označník autobusové zastávky, jízdní řád fiktivní linky 312 |
| **Kaplička sv. Floriána 1872** | kamenná deska nad dveřmi |
| čísla popisná „čp. 12“, „čp. 7“ a další | chalupy a dům mistra (čp. 3) |
| **POZOR! MINY / VOJENSKÝ PROSTOR – VSTUP ZAKÁZÁN** | červenobílé cedule po 25 m na oplocenkách a pastevních plotech podél hranice |
| **KONTROLNÍ STANOVIŠTĚ – STŮJ!** | zátarasy na silnicích A, B a cestě C |
| **Pozor! Elektrické zařízení – nebezpečí úrazu** | trafostanice (standardní výstražná značka) |
| **Honitba – vstup se psy zakázán** | jižní lesní okraj |

Značení týmů: číslo roty a jednoduchý geometrický znak (kruh, trojúhelník, čtverec) v týmové barvě na plachtě nákladního
auta a na rukávové pásce. Nepoužívají se vlajky ani reálné vojenské symboly.

---

## 8. Opotřebení a špína

Každá stopa má **fyzikální příčinu**. Špína, která nemá kde vzniknout, je chyba.

1. **Odstřik od země:** spodních 0–0,4 m fasád je tmavších a zašpiněných blátem, na straně ke dvoru nebo k cestě víc.
2. **Stékání vody:** svislé šmouhy začínají pod parapety, pod koncem okapů, u prasklých svodů a pod krycími deskami zdí.
   Šmouhy jsou široké jako zdroj a slábnou směrem dolů.
3. **Mech, řasy, lišejník:** rostou na severních a stinných plochách, na soklech, na krycích deskách opěrných zdí a na
   střešních taškách a eternitu. Na jižních, osluněných fasádách se neobjevují.
4. **Rez:** vzniká na hranách, spojích, šroubech, pantech a na spodku vrat a kontejnerů. Pod rezavým prvkem je rezavá
   šmouha. Plná rez celé plochy je jen na vracích.
5. **Opotřebení na dotykových místech:** ohlazený nátěr kolem klik, na hranách zárubní, na nášlapných hranách schodů a na
   sloupcích zábradlí. Nikdy náhodné skvrny uprostřed ploch.
6. **Provoz:** stopy pneumatik vedou do vrat, na rampu a do dvora skladu. Olejové skvrny jsou na parkovacích místech, v dílně
   pod traktorem a u sudů. Vyšlapané pěšiny vedou v trávě podél skutečných tras a v podlaze budov mezi dveřmi.
7. **Evakuace a armáda:** tu a tam odhozený předmět (taška, kolo, kočárek), otevřená branka, vytahané prádlo. Vojsko zanechalo
   pytle s pískem, HESCO, pásku a stopy pásů u zátarasů. Krev ani zničené budovy prostředí nemá, jen vypálené vraky jako
   zátarasy.
8. **Míra:** dekály špíny pokrývají nejvýš 30 % plochy fasády. Nejsilnější stopy jsou v místech zájmu (vchody, vrata, rohy).
   Detail je hustší tam, kam se hráč dívá z herní vzdálenosti (zóny, trasy), a řidší za hranicí.

---

## 9. Post-processing a co nesmí maskovat vady

### 9.1 Povolené efekty

| Efekt | Nastavení |
| --- | --- |
| tone mapping | ACES Filmic, expozice z `environment.json` (0,55) |
| adaptace oka | podle `environment.json` (`eyeAdaptation`), jen pro přechod ven a dovnitř |
| bloom | intenzita ≤ 0,15, práh nad 1,0 (jen odlesky slunce na kovu, skle a vodě) |
| vinětace | ≤ 0,15 |
| barevné korekce | neutrální, nejvýš +5 % teplejší střední tóny; žádná LUT, která mění rozpoznatelnost materiálu |
| antialiasing | SMAA nebo FXAA; TAA jen bez duchů za pohybem |
| ostření | ≤ 0,2, bez halo efektu |
| okluze (SSAO/GTAO) | jemná, poloměr ≤ 0,5 m, nikdy černé kouty; zapečené nepřímé světlo má přednost |
| hloubka ostrosti | **vypnuto ve hře**; při míření jen rozostření zbraně |
| motion blur | **ve výchozím stavu vypnuto** |
| zrno, chromatická aberace, lens dirt, lens flare | **0 / vypnuto** |

### 9.2 Co efekty nesmějí zakrývat (zadání §3.3, ENV-04)

- Každý asset se schvaluje **nejdřív s vypnutým post-processingem** (ladicí přepínač) a teprve potom se zapnutým. Vada
  viditelná bez efektů je vadou i s nimi.
- Mlha nesmí schovávat hranici mapy, přechody LOD bližší než 250 m, díry v terénu ani prázdné kulisy. Kopce se kontrolují
  s mlhou i bez ní.
- Bloom nesmí přepálit švy textur, chybějící geometrii ostění ani prosvítající hrany. Vinětace nesmí zakrýt nepřítele
  v rohu obrazu.
- Adaptace oka nesmí nahrazovat chybějící světlo v interiéru. Interiér musí být čitelný i s pevnou expozicí 0,55
  a ambientFloor 0,2.
- Barevné korekce nesmějí snížit kontrast postav proti pozadí. Kontroluje se to s postavou ve stínu u zdi dílny, na
  louce a v tmavé chodbě domu.
- Stíny nesmějí blikat při pohybu kamery (stabilní kaskády) a textura nesmí nést zapečené světlo, které odporuje slunci
  z 222°.

---

## 10. Kontrolní seznam pro každý asset

1. Měřítko je porovnané s figurou 1,80 m a s dveřmi 1,10 × 2,05 m. Pivot je na úrovni země.
2. Base colour, roughness a metallic spadají do rozsahů své rodiny (oddíl 3). V base colour není zapečené světlo.
   Normálová mapa je v konvenci OpenGL.
3. Hustota texelů odpovídá oddílu 3.5 a vzor se neopakuje v rastru pod 4 m.
4. Kolize odpovídá sémantice v `layout.json` (`meta.collision_semantics`). Okno je rovina blokující kapsli a propouštějící
   střely, keř blokuje pohyb a výhled, ne střely.
5. Asset stojí na terénu: budova na své plošině se soklem (terén mezi patkou a horní hranou soklu po celém obvodu), rekvizita
   podle `ground_fit` (rohy do 0,12 m, naklopení do 15°), nic nelevituje a nic se náhodně neprotíná (`check_layout.py` L04).
6. Opotřebení má příčinu (oddíl 8). Nápisy jsou fiktivní (oddíl 7) a paleta respektuje rezervu týmových barev (oddíl 2.3).
7. LOD zachovávají siluetu (zadání §3.1). Stromy za hranicí dál než 25 m jsou jen impostory.
8. Asset se zkontroluje na přímém slunci, ve stínu a v interiéru, s post-processingem i bez něj.

Nic z vizuálního výsledku zatím nebylo ověřeno v prohlížeči ani v UE5 (**NOT TESTED**). Tento dokument je zadání, ne
měření.
