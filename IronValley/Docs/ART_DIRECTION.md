# IRON VALLEY – výtvarný směr mapy „Kalné Hamry“

Stav: **závazné** pro tvůrce assetů (Blender skripty), pro webový renderer (three.js) a pro pozdější přenos do UE5.
Datum: 2026-09-26. Související data: `Shared/level/layout.json`, `Shared/level/buildings.json`, `Web/src/data/environment.json`,
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
18. století, dnes je z něj zámečnická dílna. Dále tu je sklad stavebnin z doby JZD, dům mistra z roku 1934, hostinec,
hasičská zbrojnice, garáže, kaplička, trafostanice a několik chalup. Obec byla před několika dny evakuována a armáda údolí
uzavřela kordonem.

Situace: **10. září 2026, 15:05 SELČ**, suché teplé odpoledne na konci léta. Slunce svítí z jihozápadu, na obloze jsou asi
3/8 kupovité oblačnosti a vzduch je lehce zakalený. Nic neprší a nic se nehýbe rychleji než listí.

Tři slova pro celou mapu: **užívané, klidné, čitelné.**

- **Užívané:** místo působí, jako by ho lidé opustili včera. Na šňůře visí prádlo, u domu stojí kolečko, v dílně je traktor
  na špalcích. Pneumatiky zanechaly stopy v blátě. Nejde o válečnou ruinu: budovy jsou celé, poškození je jen lokální
  (rozbité okno, oprýskaná omítka, vypálený autobus jako zátaras).
- **Klidné:** barvy jsou přírodní, nasycení střední, kontrast odpovídá slunečnému dni. Filmovost dává jen tone mapping,
  mírně teplé světlo a vzdušná perspektiva, nikdy barevný filtr.
- **Čitelné:** hráč musí za 0,5 s rozeznat postavu od pozadí, kryt od zakrytí a průchozí dveře od zamčených. Proto platí
  barevná rezerva v oddílu 2.3 a pravidla pro zavřené budovy v oddílu 6.4.

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
| vzdálené kopce (vzdušná perspektiva, 1–2 km) | `#7D8C86` | výsledný tón po mlze, nikoli barva textury |

### 2.2 Stavby a infrastruktura

| Materiál | Hex | Kde |
| --- | --- | --- |
| vápenná omítka lomená bílá, zvětralá | `#D8D1C1` | dílna vně, chalupy varianta C |
| omítka okrová světlá | `#C8A56E` | dům mistra, chalupa varianta A |
| cementová šedá omítka (sokly, varianta B) | `#9A968D` | |
| cihla režná (zděné pilíře, trafostanice) | `#9B5A43` | tmavší kusy `#7B4434` |
| droba – lomový kámen (sokl dílny, opěrná zeď dílny, jez) | `#6F6D63` | šedozelená |
| pískovec (opěrná zeď a schody domu) | `#B39F80` | |
| beton nový / zvětralý | `#A9A59C` / `#8F8B83` | rampa skladu, zátarasy, schody |
| vlnitý fibrocement (střecha haly) | `#8C8F8A` | s lišejníkem na severní ploše |
| pálená taška bobrovka / drážková, zvětralá | `#9A4B35` / `#7F4A3A` | přístavek dílny, dům |
| trapézový plech a sandwich panel šedozelený | `#7C857A` / `#818B80` | sklad (blízké RAL 7033) |
| vnitřní líc sandwich panelu | `#E3E2DC` | sklad uvnitř |
| ocel natřená modrošedá (zárubně, zábradlí, vrata) | `#5D6B77` | |
| pozinkovaný plech (okapy, svody, rošty) | `#A7ABAA` | kov, viz 3.4 |
| rez | `#7A4B2E` | jen na hranách a spojích |
| dřevo natřené zelené (dveře dílny, okenice) | `#3F5B45` | |
| dřevo natřené krémové / bílé (dveře a okna domu) | `#D6CCAE` / `#E6E2D8` | |
| dřevo tmavě hnědé (štítová prkna, ploty, kůlny) | `#5A4231` | |
| olejový sokl v dílně (zelená „olejová“ barva do 1,5 m) | `#5E7358` | nad ním bílá vápenná malba `#E4E0D4` |
| asfalt / ojetý pruh / záplata | `#4E4E4F` / `#605F5B` / `#3E3E40` | silnice A a B |
| žulové kostky návsi | `#8A8680` | |

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
| asfalt (`asphalt`) | 55–95, `#4E4E4F` | 0,80–0,92 (ojetý pruh 0,72–0,80) | 0 | trhliny a záplaty jako dekály |
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
| fibrocement vlnitý (`fibre_cement_*`) | 120–160 | 0,80–0,92 | 0 | |
| sklo okenní | tónování `#9AA7A6`, α 0,15–0,25 | 0,03–0,10 | 0 | odraz oblohy, ve v1 nerozbitné; špinavé sklo až 0,30 |
| polykarbonát (světlíky skladu) | 190–220, průsvitný | 0,25–0,40 | 0 | propouští světlo, neprůhledný pro výhled |

### 3.3 Kovy a nátěry kovů

| Rodina | Base colour sRGB | Roughness | Metallic | Poznámka |
| --- | --- | --- | --- | --- |
| ocel natřená (`steel_*_paint*`, `steel_blue_grey`, trapézový plech, sandwich) | podle nátěru 70–150 | 0,40–0,65 | **0** | nátěr je nekov |
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

- **Okna:** rám je osazen 0,12 m za líc fasády (hloubka ostění musí být vidět). Vnější parapet přečnívá 0,04 m
  s okapničkou. Pod parapety jsou jemné stopy stékání. Okna dílny jsou ocelová členěná (tabulky cca 0,30 × 0,40),
  v domě dřevěná zdvojená okna bílá nebo krémová, ve skladu hliníková nebo PVC s drátoskem v kanceláři.
- **Dveře:** světlá šířka ≥ 1,10 m a světlá výška ≥ 2,05 m (projektové pravidlo pro navmesh, zadání požaduje 0,90). Zárubeň
  má 0,05 m, křídlo 0,05 m a výrazný práh. Klika je ve výšce 1,05 m. Průchozí dveře stojí otevřené v klidové poloze
  (`open_deg`) a jejich křídlo se musí vejít k zarážce. Zavřené dveře neprůchozích budov popisuje oddíl 6.4.
- **Střechy:** přesah okapu 0,5 m, u štítu podle dat (`overhang_verge`). Okapy jsou půlkruhové pozinkované (125 mm), svody
  100 mm ústí do rozstřikové dlaždice, do vpusti nebo do chrliče v opěrné zdi (`downpipes[].outlet`). Voda musí mít vždy
  kam odtéct (ENV-01): dvory mají spád 1 % k vpustem nebo k potoku, opěrné zdi mají odvodňovací otvory po 2 m.
- **Napojení na terén:** terén kolem budovy leží o jeden stupeň (0,17 m) pod podlahou. Každé venkovní dveře končí na
  rovině, podestě, schodu nebo nakládací rampě. Kontroluje to `check_layout.py` (L03).

### 4.1 Dílna (bývalý hamr), `B_DILNA`

- Hamr z 18. století byl kolem roku 1924 přestavěn na cihlovou zámečnickou dílnu a od 60. let sloužil jako opravna
  zemědělských strojů. Stojí u suchého náhonu, který přiváděl vodu od jezu.
- Hala má 15,1 m světlosti a je bez stropu, s dřevěnými věšadlovými vazníky (táhla v 4,20 m). Střecha je z vlnitého
  fibrocementu, sklon 30°. Dvoupodlažní přístavek má střechu z bobrovek, sklon 35°. Obvodové zdivo je cihelné 450 mm, bývalý
  štít je dnes požární zdí.
- Vnější úprava je vápenná omítka lomená bílá (zvětralá, místy opadaná na cihlu). Sokl z lomové droby je vysoký 0,45 m.
  Uvnitř je zelený olejový sokl do 1,5 m a bílá vápenná malba nad ním.
- V kanceláři mistra v patře jsou vnitřní okna do haly (převzato z návrhu „systems“). Kancelář **není součástí zóny** a má dva
  nezávislé východy: vnitřní schodiště a venkovní ocelové schodiště s pororošty.
- Poznávací znamení: velká dvoukřídlá vrata (3,18 m světlé šířky) z prken se zeleným nátěrem, ocelový komín kamen
  a vybledlý nápis na štítu (oddíl 7).

### 4.2 Menší sklad (stavebniny), `B_SKLAD`

- Sklad hnojiv JZD z roku 1976 stojí na 1 m vysokém protipovodňovém násypu. V roce 2004 z něj firma **Stavebniny Kalina**
  udělala ocelovou halu: 5 portálových rámů po 6 m, sloupy HEA240, sandwich panely 120 mm šedozelené na betonovém soklu
  výšky 1,0 m. Střecha je z trapézového plechu, sklon 10°.
- Podlaha leží ve výšce ložné plochy nákladního auta (1,10 m nad dvorem), odtud nakládací rampa se schody a nájezdem. Zadní
  strana je zapuštěná do svahu.
- Záměrně strohá architektura potřebuje přesto stavební detaily: lemování rohů, okapové žlaby, rolovací vrata s bubnem
  a vodícími lištami, nárazníky na rampě, světlíky z polykarbonátu a oplocený dvůr (pletivo 2 m).

### 4.3 Obytný dům (dům mistra), `B_DUM`

- Zděný dvoupodlažní dům z roku 1934 má valbovou střechu z drážkových tašek, sklon 40°. Okrová omítka je hladká, šambrány
  kolem oken jsou v lomené bílé a sokl je z cementové omítky.
- Dům stojí na terase nad návsí. Terasu drží **pískovcová opěrná zeď** s betonovou krycí deskou, se zapuštěnou garáží
  (vrata jsou zavřená a vidět je jen čelo ve zdi) a se zahradními schody. Vstup vede ze dvora, kuchyňské dveře ústí do
  bočního dvorku. Balkon s plným parapetem 1,0 m je nad dvorem a má schody do zahrady.
- Interiér: terrazzo v chodbách, dlažba v kuchyni a koupelně, parkety v pokojích, bílé dveře.

### 4.4 Vedlejší budovy (vždy `"enterable": false`)

Hostinec U Hamru (zabedněný), Hasičská zbrojnice se sušicí věží, řadové garáže (3 boxy), kaplička sv. Floriána, zděná
trafostanice, autobusová zastávka (otevřená, jediná přístupná, bez interiéru), stánek s roletami, kůlny, dřevník, seník,
stodola, kolna na stroje, kancelář štěrkovny (kontejner) a čtyři uzavřené chalupy ve variantách A (okrová, taška), B (šedá
omítka, eternit) a C (bílá, červená taška, zabedněná okna v přízemí). Tvar, výška a sklon střechy jsou v `layout.json`
(`secondary_buildings`).

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

Uvnitř hrací plochy rostou **jen listnaté dřeviny** (zadání §3). Jehličnany se smějí objevit jen v kulisách vzdálených
kopců (nad 260 m od středu). Živé ploty uvnitř mapy jsou habrové nebo z ptačího zobu, nikdy z túje.

### 6.1 Stromy (`trees.species`, 1626 instancí)

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
| `briza` | bříza bělokorá (*Betula pendula*) | 15 / 3,5 m | náletové okraje, u štěrkovny |
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

### 6.4 Zavřené budovy a čitelnost průchodnosti

- Neprůchozí budova se musí **číst jako zavřená na první pohled**. Používá se zavřená okenice, zabedněné okno (OSB,
  zvětralé), visací zámek s řetězem, rezavá rolovací vrata, zatlučené dveře nebo cedule „ZAVŘENO“. Konkrétní řešení každé
  budovy určuje `reads_closed_by` v `layout.json`.
- **Žádné falešné dveře:** dveře, které vypadají průchozí (pootevřené, s tmavou mezerou, s osvětleným interiérem), se
  smějí objevit jen na průchozích budovách. Okna zavřených budov mají za sklem tmavou záclonu nebo desku, nikdy černou
  díru ani prázdný interiér.
- Průchozí dveře jsou naopak otevřené a v otvoru je vidět světlo interiéru.

---

## 7. Nápisy a značení (vše fiktivní)

Používají se jen **fiktivní** místní názvy a firmy. Nesmí se objevit reálné značky, loga, SPZ ani insignie skutečné armády.
Písmo dopravních značek je bezpatkové technické (volně licencované písmo DIN-like). Starší nápisy jsou ručně malované
patkovým písmem, vybledlé.

| Nápis | Kde |
| --- | --- |
| **Kalné Hamry** | tabule začátku obce na silnicích A a B (bílá s černým lemem) |
| **Dolní Hamry 2 km** | směrovka na silnici A za zátarasem Alfy |
| **Štěrkovna Horní Hamry – vstup zakázán** | brána štěrkovny za spawnem Bravo |
| **Hostinec U Hamru** | štít hostince, pod ním cedule „ZAVŘENO“ a vybledlá reklama na limonádu bez značky |
| **Stavebniny Kalina** | štít skladu nad rampou, menší cedule „Otevírací doba Po–Pá 7–16“ |
| **JZD Kalné Hamry – sklad hnojiv 1976** | vybledlý malovaný nápis na betonovém soklu skladu (pod novým obkladem prosvítá) |
| **Kalina a syn – zámečnictví** | vybledlý nápis na štítu dílny (přestavba 1924) |
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
5. Asset stojí na terénu (±0,15 m), nic nelevituje a nic se náhodně neprotíná.
6. Opotřebení má příčinu (oddíl 8). Nápisy jsou fiktivní (oddíl 7) a paleta respektuje rezervu týmových barev (oddíl 2.3).
7. LOD zachovávají siluetu (zadání §3.1). Stromy za hranicí dál než 25 m jsou jen impostory.
8. Asset se zkontroluje na přímém slunci, ve stínu a v interiéru, s post-processingem i bez něj.

Nic z vizuálního výsledku zatím nebylo ověřeno v prohlížeči ani v UE5 (**NOT TESTED**). Tento dokument je zadání, ne
měření.
