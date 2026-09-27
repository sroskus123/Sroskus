# IRON VALLEY – rozhodnutí podle referencí uživatele

Stav: 2026-09-27. Rozbor obrázků je v `Docs/REFERENCE_ANALYSIS.md`, srovnání letecké reference s plánem v
`Docs/img/reference_vs_plan.png`. Data vznikají jen generátorem (`Tools/level/run_pipeline.py`, rozhodnutí D10);
každé rozhodnutí níže je v něm zapsané a `Tools/level/check_layout.py` hlídá jeho důsledky.

Zásada: **vzhled podle referencí, rozměry a rozmístění podle hratelnosti.** Kde se obojí nedá splnit, rozhoduje
vyváženost (spawn → zóna max/min ≤ 1,06, ±10 %), bezpečnost spawnů (žádná viditelnost, i u záložních řad), průchodnost
pro AI (Recast, kapsle r 0,35 m) a „nic nesmí levitovat“.

| # | Rozhodnutí | Reference | Kompromis / důvod |
| --- | --- | --- | --- |
| R-01 | **Dílna jednopodlažní, tvar L** jako na ref. 04: hala 14,5 × 10 m (okap 4,60, 30°), ustoupený přístavek 6,5 × 7,8 m, pultová kůlna 3,5 × 5 m, dva cihlové komíny, světlík, dvoje vrata; vše průchozí (hala, výdejna, šatna, kompresorovna) | 02, 04 | Zmizelo patro s kanceláří z dřívějšího návrhu. Zóna Dílna je tím celá v jedné výškové hladině (žádné sporné z-pásmo), kovárna a kamna dávají komínům smysl. |
| R-02 | Vrata `DL_G2` jsou v modelu **otevřená** (na ref. 04 zavřená) | 04 | Hala potřebuje dva široké vstupy z dvora + zadní dveře + dvoje štítové dveře, jinak je zóna snadno uzavíratelná. |
| R-03 | **Sklad 25 × 12,5 m** z režných cihel s omítnutými pilastry, zeleno-šedá vlnitá střecha 20°, posuvná vrata (vpředu 1 otevřená + 1 zavřená, vzadu 1 otevřená), rampa 1,10 m s přístřeškem | 01, 03 | Letecký pohled naznačuje delší halu (45–50 m) a plochý přístavek na východě; délka podle ref. 03 (měřítko nákladní auto) a velikosti zóny (400–600 m²). Přístavek nahrazuje **zadní dvůr** na plošině (flank Brava). Plošina je zaříznutá do svahu a drží ji opěrná zeď `RW_SKLAD_NE`; čelo rampy i její severní konec jsou terénní stupeň (`RW_SKLAD_DOCK`, `RW_SKLAD_DOCK_N`), na rampu se z dvora dostane jen po `SK_X1`, `SK_X2`, `SK_X3`. |
| R-04 | **Dvoupodlažní dům s červenou taškovou valbou** a přízemním křídlem, zahrada obehnaná zdí 1,8 m + omítnutá zeď terasy 1,0 m | 01 | Orientace ponechána: zahrada je obrácená k návsi (sever), celá kompozice z ref. 01 (zahrada před domem, křídlo vpravo při pohledu ze zahrady) je proto otočená o 180°. Zóna Dvůr tak zůstává přístupná z návsi po schodech ve zdi. |
| R-05 | **Kaple se zvoničkou v klínu silnic** + nízká omítnutá zídka 1,1 m | 01, 03 | Zídka je nízký kryt u křižovatky; kaple je nevstupná (dveře zavřené, tmavé okno). |
| R-06 | **Kůlna R05 se opakuje** (`S_KULNA`, `S_KULNA_DUM`, `S_KULNA_2`, `S_KULNA_3`, `S_PILA_BUDKA`), vždy nevstupná a čitelně zavřená | 05 | Žádné falešné dveře; kolize = celý půdorys. |
| R-07 | Chalupy = zavřené domy (`S_DOMEK_1–4`), `S_DOMEK_4` kamenná varianta | 01 | Vstupné jsou jen tři hlavní budovy (zadání). |
| R-08 | **Potok + betonové lávky** (deska 0,30 m, zábradlí R16) + **betonový most** (deska 0,55 m, sloupky s trubkami); prostor pod mosty je nižší než 2,10 m, proto ho uzavírají ocelové česle | 01, 02 | Žádné průlezy jen v dřepu (hráč by se schoval tam, kam bot nemůže). |
| R-09 | Zastávka R06 (dřevěná), sloupová trafostanice, **dřevěné sloupy vedení R07** s lampami, pletivo na podezdívce R14, nízké betonové zídky, palety R08, sudy, VZV, vojenský vůz (statický) | 02, 03, R06–R08, R14, R16 | Sloupy blokují pohyb (r 0,14 m), výhled ne. Pletivo je průhledné pro výhled i střelbu (kryje jen podezdívka 0,35 m). |
| R-10 | **Slunce 222° / 38° a oblačnost 0,4** ponechány z `Web/src/data/environment.json` | 02, 03 (nižší pozdní slunce, rozpadlé kupy) | `environment.json` je jediný zdroj světla pro všechny mapy (D9). **Otevřená otázka** pro uživatele: má mapa dostat vlastní pozdější čas a víc mraků? |
| R-11 | **Mokrý asfalt a kaluže** (jen vzhled: nižší roughness, odlesky, kaluže jako dekály) | 02, 03 | Bez vlivu na hratelnost (žádné zpomalení, žádné stopy). |
| R-12 | **Jen fiktivní názvy:** Kalné Hamry, Kalný potok, Nové Kalno (směrovka), Štěrkovna Kalný Vrch, Kalina a syn, JZD Kalné Hamry | review P2-REAL-TOPONYMS | Dřívější názvy štěrkovny a směrovky byly skutečné místní části; `check_layout.py` C01 drží seznam zakázaných názvů. „Kalný potok“ je obecné jméno, které se v ČR může vyskytovat – **otevřená otázka**. |
| R-13 | **Okraj mapy je fyzický:** kruh bariér 0,5 m uvnitř tvrdé hranice (lesní oplocenka, pastevní a dřevěný plot, plot štěrkovny, zátarasy na silnicích), cedule po 25 m | review P1-EDGE, R07 (sloupy za hranicí) | `check_layout.py` BND2 vzorkuje tvrdou hranici po 2 m. |
| R-14 | **Každá vedlejší budova stojí na srovnané plošině** se soklem 0,30 m (patka 0,15 m pod terénem, stupňovitý sokl tam, kde silnice sahá do plošiny); rekvizity na svahu se naklápějí (`ground_fit: tilt`), hromady a moduly kopírují terén (`conform`), svislé drobnosti mají patku (`upright_footing`) | 05 (sokl kůlny), review P1-SEC-CONTACT | `check_layout.py` L04 vzorkuje celý půdorys a rohy rekvizit. |
| R-15 | Spawn řady přepočítané: alfa pro Sklad s = 85 (dřív 84), bravo pro Dílnu a Sklad s = 158 (dřív 157) | – | Plošina skladu a plošiny budov posunuly vzdálenosti; FMM max/min 1,044 / 1,048 / 1,033. |
| R-16 | **Průstřelnost a výhled:** dřevěné bedny a palety průstřelné (nízký kryt), keře a živé ploty zakrývají výhled, ale kulku nezastaví, pletivo je průhledné, betonové zídky a HESCO kryjí | R08, R13, R14 | Spawny jistí jen tvrdá geometrie (HESCO, kontejnery, budovy); LOS test vegetaci ignoruje. |
| R-17 | **Jehličnany:** smrk a borovice na lesních svazích a u hranice; uvnitř hrací plochy nejvýš 12 % stromů a ne blíž než 3 m od zón a spawnů | R11, 01–03 | Zadání chce listnaté stromy; reference ukazují smrky na okrajích – kompromis hlídá G01. |
| R-18 | Zadní odbočka ke skladu (`TRACK_SKLAD_REAR`) odbočuje z východní polní cesty tam, kde je cesta už ve výšce dvora (z ≈ 2,6), a vede skoro po rovině | review P2-STEEP-PATHS | Dřívější nájezd 22° zrušen; cesty mají reálné sklony (silnice ≤ 8°, polní cesty ≤ 12°, pěšiny ≤ 20°, R05). |

## Otevřené otázky pro uživatele

1. Čas a oblačnost mapy (R-10): ponechat společné nastavení, nebo pozdější odpoledne s rozpadlou kupovitou oblačností jako na
   referencích 02 a 03?
2. Délka skladu (R-03): stačí 25 m, nebo má mapa dostat delší halu a plochý přístavek z leteckého pohledu (zóna by se musela
   přeskládat)?
3. Jméno potoka „Kalný potok“ (R-12): ponechat obecný hydronym, nebo vymyslet zcela jedinečný?
4. Vrata `DL_G2` (R-02): otevřená kvůli hratelnosti, nebo zavřená jako na obrázku (dílna by pak měla jen jeden široký vstup)?
