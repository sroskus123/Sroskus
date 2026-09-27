# Hlavní prompt pro Claude Code / Claude Opus

**Projekt:** IRON VALLEY — pracovní název originální realistické vojenské FPS inspirované atmosférou WARDOGS.  
**Druh zadání:** vytvoření a místní spuštění hratelného prototypu.  
**Datum přípravy:** 26. 9. 2026.  
**Povinná příloha:** `02_PRAVIDLA_KVALITY_A_TESTY.md`.

## Jak oba soubory použít

Vlož oba soubory do projektu Claude Code nebo je připoj ke zprávě. Do chatu napiš: „Přečti oba soubory celé a realizuj zadání. Začni kontrolou prostředí a pokračuj implementací.“ Použij Claude s přístupem k pracovnímu adresáři, terminálu a potřebným aplikacím. Připojení Higgsfieldu v jiné aplikaci nebo jiném chatu samo o sobě nedokazuje jeho dostupnost v tomto prostředí.

Tento dokument neurčuje konkrétní obchodní označení nebo číslo verze modelu Claude. Důležitá je jeho schopnost pracovat s kódem, nástroji, soubory a skutečným výstupem hry.

---

## ZAČÁTEK ZADÁNÍ PRO REALIZACI

Jsi zkušený vývojář her v Unreal Engine, technický výtvarník a autor herních systémů. Tvým úkolem je **vytvořit skutečnou, hratelnou a vizuálně propracovanou vojenskou FPS**, nikoli pouze návrh, video, galerii obrázků nebo menu bez hry.

Chci zážitek podobného typu jako WARDOGS: moderní pěchotní boj, důležité krytí, terén, boj o území a uvěřitelný vojenský svět. Vytvoř vlastní mapu, pracovní název, vizuální identitu a vlastní či řádně použitelné assety. Z WARDOGS přebírej inspiraci žánrem a atmosférou, nikoli jeho soubory, přesnou mapu nebo značku.

Prioritou jsou **dobré modely, kvalitní textury, ruce a prsty, přirozené animace, smysluplní nepřátelé, fyzika a uvěřitelné budovy**. Chci menší hotový kus hry, na kterém je kvalita vidět z první osoby i při pohledu zblízka. Obrovská prázdná mapa by můj požadavek nesplnila.

Nejprve přečti oba soubory celé. Příloha s kvalitou je součástí zadání, nikoli volitelné doporučení. Aktuální výslovná změna od uživatele má přednost. Běžná rozhodnutí udělej samostatně a stručně je zaznamenej. Po analýze pokračuj do realizace; nezastavuj práci otázkou, zda máš začít.

## 1. Technické rozhodnutí

Použij **Unreal Engine 5 pro hru, Blender pro tvorbu a úpravy assetů a dostupné nástroje Higgsfield pro vhodnou část tvorby modelů, podkladů nebo animací**.

| Nástroj | Úloha v tomto projektu | Podmínka použití |
| --- | --- | --- |
| Unreal Engine 5 | Herní logika, obraz, kolize, AI, animace ve hře, ovládání a místní spuštění | Použij kompatibilní dostupnou stabilní verzi; zapiš přesné číslo verze |
| Blender | Geometrie, UV, materiály, kostry, váhy, opravy animací a export | Místní instalace nebo skutečně dostupný Blender v Higgsfieldu |
| Higgsfield | Generování 3D podkladů/modelů, dostupný rigging, animační podklady a případně 3D Jutsu | Nejdřív ověř konkrétní nástroje, oprávnění, parametry a výstupní formáty |
| Unity | Možná alternativa při pozdější změně priorit | Nepřeváděj na něj projekt automaticky; v tomto zadání je zvolen Unreal |

Blender není náhrada herního enginu. Higgsfield nenahrazuje logiku FPS ani validaci animací v enginu. Unreal sám nezaručuje kvalitní výsledek: rozhodují assety, měřítko, animace, světlo a provedení.

### 1.1 Nejdříve prověř prostředí

Ověř operační systém, dostupnost Unreal Editoru, vhodného C++ toolchainu, Blenderu, grafického zařízení, volného místa a přístup k souborům. Zkontroluj aktuální projekt a případné místní instrukce. Uveď, zda umíš aplikaci skutečně spustit a zda její okno umíš sledovat.

Zaznamenej přesnou verzi enginu a použitých pluginů. Verze během rozpracované fáze svévolně neměň. Dostupnost konkrétního API ověřuj proti instalované verzi, nikoli podle paměti na jiné vydání.

Vytvoř krátkou tabulku dostupnosti: Unreal, build, Blender, Higgsfield, import assetů, render, místní spuštění, prohlížečový test. Každá položka má stav `OVĚŘENO / CHYBÍ / NEOVĚŘENO` a konkrétní důkaz nebo překážku.

Pokud nástroj chybí, neoznamuj, že jej používáš. Připrav vše, co je bez něj skutečně proveditelné, a uveď nejmenší konkrétní krok potřebný k odblokování. Případný požadavek na přihlášení, instalaci velkého enginu nebo přístup formuluj přesně. Nezastavuj kvůli tomu nezávislé práce na projektu.

### 1.2 Jak chápat požadavek „jen to spustit, nedělat soubor ke stažení“

Interní zdrojové soubory, Unreal projekt, mapy a assety samozřejmě vytvářej a ukládej. Požadavek znamená, že finální předání této fáze má být **místně spuštěná testovatelná hra**, ne instalační balík, archiv nebo publikace na Steamu.

Výchozí způsob testu je Play In Editor a následně Standalone Game. Výstupem není povinně zabalený distribuční build. Ulož otevřitelný projekt a přesný postup dalšího spuštění.

Pokud je v daném prostředí proveditelný prohlížečový test, připrav navíc lokální **Pixel Streaming**. Unreal při něm běží jako nativní aplikace a do prohlížeče se přenáší obraz a ovládání. Neoznačuj jej jako běžný export Unreal hry do HTML nebo WebGL. Kompatibilní plugin, infrastrukturu, spuštění aplikace i příjem vstupu ověř podle skutečné verze enginu.

Použij volný lokální port a zveřejni až ověřenou adresu. Ověř propojení Unreal aplikace se streamem, obraz, zvuk a ovládání. Pouhá načtená webová stránka není úspěšný test hry. Nepřerušuj kvůli portu cizí běžící služby. Nezpřístupňuj test veřejně, pokud uživatel požaduje jen místní zkoušku.

`localhost` patří vždy počítači, na kterém se otevírá. Jestli pracuješ na vzdáleném stroji, netvrď uživateli, že jeho vlastní localhost automaticky otevře tvůj server. Použij skutečně dostupný podporovaný náhled nebo jasně uveď místní způsob spuštění na jeho stroji.

Pokud Pixel Streaming nejde zprovoznit, dokonči nativní hratelný test a samostatně označ prohlížečovou variantu jako nedokončenou. Nepřepisuj bez dohody celou hru do jednoduššího webového enginu jen kvůli adrese v prohlížeči.

## 2. Rozsah první hratelné verze

Vytvoř kvalitní **vertical slice**, tedy malou kompletní ukázku všech podstatných částí hry. Následující čísla jsou výchozí návrh tohoto projektu, ne popis WARDOGS ani naměřené výsledky.

| Oblast | Povinný výchozí rozsah |
| --- | --- |
| Perspektiva | FPS s detailními pažemi a rukama, plnými modely ostatních vojáků |
| Mapa | Přibližně 350 × 350 metrů; kompaktní průmyslová vesnice v členitém údolí |
| Bojující | Tři týmy po šesti: hráč + pět spojenců, dalších dvanáct botů |
| Ověření během vývoje | Začni třemi boty; před dokončením ověř všech sedmnáct |
| Herní režim | Boj tří týmů o jednu aktivní kontrolní oblast |
| Délka kola | Deset minut nebo dosažení cílového skóre |
| Zbraně | Jedna výborně zpracovaná puška; pistole po dokončení pušky |
| Budovy | Tři odlišné hlavní typy; nejméně dva plně průchozí interiéry |
| Fyzika | Pohyb, zásahy, stabilní ragdoll, dveře a vybrané malé předměty |
| Dokončení | Úvodní obrazovka, výběr základní výbavy, hra, smrt/respawn, výsledek a nové kolo |

Nedělej v této fázi veřejný multiplayer pro sto lidí, rozsáhlou ekonomiku, celou vozovou flotilu, obrovský otevřený svět ani kompletně zničitelné město. Architekturu připrav rozumně pro pozdější rozšíření, ale neslibuj ověřený multiplayer jen proto, že je kód rozdělený do komponent.

Pokud rozsah začne ohrožovat kvalitu, nejdřív omez vedlejší dekorace a doplňkové systémy. Povinné funkce nebo počet botů nepovažuj za splněné, pokud je vynecháš. Takové omezení explicitně uveď jako změnu rozsahu nebo nehotovou položku.

### 2.1 Výchozí pravidla kontrolního bodu

Připrav tři otestovaná umístění oblasti a při zahájení kola vyber jedno. V první verzi zůstává aktivní oblast na místě, aby se dalo spolehlivě ověřit chování týmů.

Kontrolu získává tým s jednoznačně největším počtem živých členů v oblasti. Při shodě se bodování zastaví; předchozí vlastník nesmí dostávat body z chyby v cache. Prázdná oblast neboduje. Mrtví, respawnující a neaktivní účastníci se nepočítají.

Výchozí nastavení je jeden bod každé dvě sekundy platné kontroly a cíl sto bodů. Po uplynutí deseti minut vyhraje tým s největším skóre; shoda znamená remízu. Všechny hodnoty musí být datově nastavitelné. Jde o vlastní jednoduchá pravidla prototypu.

Přidej bezpečně umístěné týmové spawny, krátkou čitelnou prodlevu respawnu, doplnění základní výbavy a úplné vynulování kola při restartu. Spawn se nesmí objevit uvnitř předmětu nebo přímo v obsazeném nepřátelském prostoru.

## 3. Výtvarné zadání

Moderní evropské průmyslové údolí: nízká zástavba, dílna, menší sklad, obytný dům, dvory, polní cesta, asfalt, příkop, opěrná zeď, listnaté stromy a vzdálené kopce. Vojenské prostředí má působit užívaně, nikoli jako sterilní výstava modelů. Barevnost má být přirozená a čitelná, se zdrženlivým filmovým zpracováním.

Založ měřítko na dospělém člověku. Dveře, kliky, parapety, schody, zbraně, auta jako statické rekvizity a vegetace musí patřit do stejného světa. Modely nesmějí létat nad zemí ani se náhodně protínat.

### 3.1 Shoda s referenčními obrázky

Pokud uživatel dodá obrázek, ber jej jako konkrétní výtvarnou referenci. Před modelováním sepiš siluetu, proporce, hlavní objemy, důležité detaily, materiály a nejistoty na neviditelných stranách. Netvrď, že jediný obrázek přesně určuje zadní stranu nebo rozměry.

Když obrázky chybí, vytvoř jednotné referenční podklady a popiš vlastní zvolené proporce. Nové generace jednoho assetu nesmějí svévolně měnit jeho tvar. Model porovnávej s referencí při obdobném úhlu kamery a ohnisku.

**Detail viditelný z herní vzdálenosti nesmí zmizet jen proto, že je jednodušší postavit několik kostek.** Optimalizace je přípustná, pokud zachová rozpoznatelnou siluetu, proporce a důležité materiálové vlastnosti. Hodnoť herní výsledek, ne samotný počet polygonů.

### 3.2 Budovy

Každá hlavní budova potřebuje čitelný architektonický účel: základy, tloušťku stěn, osazená okna, dveřní rám, střechu, okapy nebo věrohodně řešený odvod vody, prahy a napojení na terén. Střecha má přesah a skutečný tvar, fasáda má hloubku. Záměrně strohá skladová architektura může být jednoduchá, ale musí mít odpovídající stavební detaily.

V průchozích budovách vytvoř konzistentní vnitřní a vnější rozměry, rozumný půdorys a funkční přístup. Dveře a okna, které hráče vybízejí ke vstupu nebo výhledu, nesmí skrývat nepopsanou kolizní stěnu. Neprůchozí objekty musí být čitelné a nemají slibovat přístupný prostor.

Rozmístění krytů, oken a střeleckých pozic odvozuj od boje a pohybu AI. Detaily přidávej tam, kde mají význam, a hlídej konzistentní měřítko a výkon.

### 3.3 Terén, obloha a atmosféra

Terén musí mít plynulé svahy, přirozené nerovnosti, čitelné cesty a věrohodné přechody materiálů. Vyřeš kontakt budov a kamení s povrchem, vegetaci podle sklonu a vlhkosti a okraj mapy začleněný do prostředí.

Použij vhodně nastavenou atmosféru, sluneční světlo, oblohu, mraky a jemnou mlhu. Směr slunce, stínů a osvětlení mraků má být konzistentní. Pro první verzi zvol jednu propracovanou denní situaci; proměnlivé počasí není podmínkou.

Mraky nesmějí vypadat jako ploché náhodné skvrny, nízké rozlišení na kouli nebo hlavní zdroj časového blikání. Testuj obraz i za pohybu. Zkontroluj expozici při přechodu ven/dovnitř, ostrost, odrazy a stabilitu stínů. Hloubka ostrosti, bloom, mlha a motion blur nesmějí maskovat vady modelů.

## 4. Povinné zapojení Higgsfieldu a tvorba assetů

Higgsfield skutečně využij na vhodnou část tvorby. Neomezuj splnění požadavku na větu v dokumentaci. V seznamu assetů dolož alespoň jeden použitý model nebo animační podklad: odkud přišel, jak byl upraven a kde je ve hře použit. Samotné propagační video mimo hru není splnění.

K datu přípravy zadání byly v připojeném prostředí dostupné rodiny nástrojů pro image-to-3D, multi-image-to-3D, humanoidní rigging a předpřipravené animační klipy, a také 3D Jutsu s Blenderem. **Tuto dostupnost ověř znovu přímo ve svém prostředí.** Rozhraní v Claude může mít jiné názvy, oprávnění nebo funkce.

### 4.1 Pracovní postup

1. Zjisti dostupná připojení a načti skutečné popisy potřebných nástrojů. Ověř formáty, limity a případný kreditový rozpočet. Nevymýšlej API adresy ani ID modelů nebo animačních akcí.
2. Pro složitý objekt připrav konzistentní pohledy. Když nástroj podporuje více referencí, používej různé pohledy téhož objektu, ne náhodné podobné obrázky.
3. Nejdříve ověř jediný kompletní průchod: vstup → model → případný rig → export → import do enginu → skutečný herní pohled. Hromadná výroba před ověřením přenosu zbytečně násobí chyby.
4. Výstup prohlédni včetně zadní strany a míst, která obrázek neukazoval. Oprav geometrii, proporce, UV, tvrdé hrany, normály, materiály a potřebné oddělení částí.
5. U postav ověř kostru, orientaci kloubů, váhy a prsty. Automatický rig není důkaz správné anatomie ani hotové animace.
6. Animace uprav na konkrétní postavu a zbraň, zkontroluj kontakty a přenos do Unrealu. Videoklip může sloužit jako pohybová reference; neobsahuje automaticky použitelnou kosterní animaci.
7. Změř měřítko, vytvoř vhodné kolize a nastavení výkonu, importuj asset a znovu jej prohlédni ve hře.

Pokud máš dostupné 3D Jutsu, před úpravou zjisti skutečný projekt, revizi a stav scény. Dodržuj aktuální pravidla nástroje pro úpravy, běžící operace a import. Nehádej revize, názvy objektů ani ID assetů. Po změně ověř obraz z vyrenderované scény; úspěšné spuštění skriptu samo vzhled nekontroluje.

Některá rozhraní pro import do 3D Jutsu přijímají jen položky vlastního katalogu. Nepředpokládej, že přijmou libovolné GLB z generátoru. V takovém případě použij podporované stažení do místního Blenderu a pokračuj tam; neobcházej omezení importu skriptem stahujícím cizí data uvnitř vzdáleného Blenderu.

Pokud Higgsfield není připojený, pojmenuj chybějící krok a pokračuj na enginu a lokálně dostupných assetech. Finální report musí uvádět, že povinné zapojení zatím chybí. Nenahrazuj ho potichu jinou službou. Placené generace drž v uživatelem schváleném rozpočtu; opakované slepé generování není opravný postup.

### 4.2 Přenos do Unrealu

Uchovej upravitelný zdroj a exportované assety. Formát zvol podle skutečně podporovaného importu v dané verzi enginu; GLB pro přenos neznamená automaticky bezchybný import všech funkcí. Pro kosterní model a animace může být vhodný export z Blenderu do FBX, pokud je jeho import ověřený.

Sjednoť metry/centimetry a orientaci os. Ověř testovací metr a výšku postavy. Zkontroluj root bone, transformace, skin weights, délku klipů, snímkovou frekvenci a materiály. Constraints a procedurální materiály podle potřeby převáděj do přenositelných dat. Jednu změnu měřítka neaplikuj dvakrát.

Veď jednoduchý asset manifest: název, autor/zdroj, podmínky použití, reference, zdrojový soubor, export, cesta v Unrealu, provedené opravy a stav kontroly. Nepředpokládej, že každý katalogový nebo generovaný model je rovnou vhodný do hry.

## 5. Postavy, ruce a animace

Postavy mají realistické dospělé proporce, přirozenou délku končetin, stabilní ramena, lokty, zápěstí, kyčle, kolena a kotníky. Helma, vesta a výstroj se nesmějí chovat jako měkká součást těla. Výstroj potřebuje rozumné napojení na kostru.

Každá viditelná ruka má pět správně umístěných prstů. Palec stojí proti ostatním prstům. Nesmějí srůstat, křížit se přes sebe nebo se lámat při stisku. Rukavice anatomické chyby neschovají. Především FPS ruce kontroluj v detailu při pohybu, míření i přebíjení.

Pravá ruka drží rukojeť přirozeně, podpůrná ruka odpovídá předpažbí. Pažba a tělo postavy nesmějí mít nesmyslný odstup. Prst u spouště je součástí řízené pózy, ne náhodný výstupek sítě. Pro pohyby potřebné ve hře vytvoř skutečné klipy a odpovídající přechody.

### 5.1 Požadované pohyby

| Skupina | Požadované stavy a přechody |
| --- | --- |
| Lokomoce | Idle, start/stop, chůze, běh, sprint, pohyb vzad a do stran |
| Změna postoje | Stoj ↔ dřep, pohyb ve dřepu, bezpečné vstávání |
| Směr | Otočení na místě, změna směru za pohybu, návaznost trupu a nohou |
| Terén | Schody, svahy, překročení malé nerovnosti, pád a doskok |
| Zbraň | Zvednutí, držení, míření, výstřel, přebití s nábojem i z prázdna |
| Bojové reakce | Střídmá reakce na zásah, smrt a stabilní přechod na ragdoll |

Použij vhodný Animation Blueprint, blendování, IK a retargeting. Složitější systém typu Motion Matching zvol jen tehdy, máš-li vhodná data a přináší skutečný přínos. Menší kvalitní sada konzistentních animací je přijatelný základ.

Rychlost animace musí odpovídat skutečnému pohybu kapsle. Pro běžnou lokomoci stanov jednoho vlastníka pohybu. Výchozí volba může být Character Movement s in-place animacemi; root motion používej řízeně pro konkrétní akce. Nikdy neposouvej postavu současně dvěma nezávislými systémy.

Chodidla během opory nesmějí bruslit po zemi. IK má upravovat kontakt a polohu pánve v přiměřeném rozsahu; nesmí natahovat nohy přes celé schodiště. Kolena se neobracejí dozadu, délky kostí zůstávají stabilní. Krok přes několik metrů není přípustný způsob překonání rozdílu mezi animací a pohybem.

## 6. Zbraně a střelba

Nejdřív dokonči jednu pušku včetně celého obslužného cyklu. Poté přidej pistoli. Každá musí mít čitelnou hlaveň, tělo, rukojeť, zásobník, mířidla, smysluplné proporce a povrchy odlišující kov, polymer, gumu a sklo. Zbraň nesmí být jen kvádr pokrytý obrázkem zbraně.

Pohyblivé části odděl tam, kde je animace potřebuje. Přebíjení musí prostorově a časově odpovídat zbrani: kontakt se zásobníkem, jeho vyjmutí, založení a další potřebný pohyb. Zásobník nesmí skočit z ruky do jiného místa ani se zdvojit. Přerušení přebíjení nesmí přidávat munici dvakrát nebo nechat ruku zamčenou mimo zbraň.

Implementuj odezvu výstřelu, střídmý recoil, zvuk, vizuální účinek u ústí, zásah povrchu a poškození. Základní munici a rychlost palby ulož do dat. Neopírej výpočet střelby o délku snímku.

Výchozí střelba může být raycast se zdokumentovaným chováním. Kamera určuje zamýšlený cíl, ale pro zásah musí být ověřena cesta od ústí hlavně. Hráč nesmí střílet skrz zeď jen proto, že kamera vidí za roh. Pokud implementuješ skutečné projektily, jejich test musí pokrýt rychlý pohyb a průlet tenkou kolizí.

Rozliš kamerový a herní recoil, plynulé ADS a omezení zbraně blízko stěny. Polohu zbraně a FOV neohýbej tak, aby vznikaly deformované prsty nebo klamná mířidla. Přidej nastavitelné FOV, citlivost a intenzitu pohybu kamery.

## 7. Nepřátelé a spojenci

AI má používat skutečné informace z herního světa: zrak, sluch, zásah a poslední známou pozici. Nemá automaticky znát aktuální polohu hráče za zdí. Po ztrátě kontaktu musí pátrat podle omezené paměti a přestat sledovat cíl, o kterém nemá nové informace.

Použij AIController a přehledně zvolený rozhodovací systém, například Behavior Tree. Zajisti navigaci po mapě, týmovou příslušnost, vnímání a přidělování úkolů. EQS nebo obdobný výběr krytů použij jen tam, kde je opravdu implementovaný a ověřený.

Povinné chování: přesun k cíli, pozorování, reakce na kontakt, výběr použitelného krytu, zamíření, krátké dávky, přebití, změna pozice, pátrání a návrat k úkolu. Nepřítel nemá být pouze model běžící přímo na hráče.

Týmy bojují i mezi sebou a obsazují oblast bez přítomnosti hráče. Spojenci se řídí stejnými základními pravidly pohybu, munice a viditelnosti. Reakční prodlevu, rozptyl a rozhodovací intervaly nastav datově. Nevyrob automatického odstřelovače s okamžitým zaměřením.

Při pohybu více botů řeš vyhýbání a dostupnost krytů. Bot nesmí donekonečna tlačit do kolegy nebo zabrat stejné místo jako jiný. Zaseknutí vede k novému výpočtu cesty nebo změně cíle. Viditelný teleport v boji není oprava navigace.

AI animace musí respektovat skutečnou rychlost, zrychlení, směr a postoj. Bot nestřílí během neukončeného přebití, nemíří ramenem dozadu a neotáčí celé tělo o 180 stupňů v jediném snímku. Vzhled, logika a kolize musí představovat tutéž postavu.

## 8. Fyzika, kolize a materiály

Fyzika má být stabilní a uvěřitelná pro hru. Používej rozumné jednotky, hmotnosti, těžiště, gravitaci a tlumení. Neměň gravitaci nebo měřítko celé hry jako náhradu opravy importu.

Pohyb řeš kolizně s kontrolou překážek. Vyřeš schody, maximální sklon, dřep pod překážkou, prostor pro vstání, pád a dopad. Velkou překážku nesmí postava automaticky považovat za jeden schod. Nepřesouvej ji skrz stěnu přímým zápisem pozice.

Ragdoll musí mít správné kloubní limity, stabilní přechod z animace, rozumné impulsy a deaktivaci AI po smrti. Nesmí explodovat kvůli vzájemně překrytým kolizním tělesům. Počet aktivních těl a drobných předmětů omezuj podle měření výkonu.

U dveří vyřeš osu otáčení, tloušťku, zarážku a interakci s postavami. Pro těžké stavební objekty použij statickou kolizi; dynamiku přidávej pouze tam, kde má herní smysl. Rozbíjení skla nebo malých rekvizit je bonus až po dokončení základů.

Materiály navrhuj jako čitelné PBR povrchy. Zkontroluj barevné prostory, mapování kanálů a orientaci normal map. Kov, omítka, látka, kůže, bláto a polymer nemají sdílet tentýž lesk. Textura nemá obsahovat nahodilé upečené světlo, které odporuje světlu v herní scéně.

## 9. Ovládání, zvuk a uživatelské rozhraní

Zaveď běžné FPS ovládání: WASD, myš, střelba, míření, přebití, sprint, dřep, interakce a menu. Skok je střídmý a kolizně kontrolovaný. Změnu vazeb připrav datově. Ovládání vysvětli přímo v testovací verzi.

HUD ukazuje zdraví, munici, aktivní oblast a skóre týmů. Přidej jasnou identifikaci spojenců a výsledek kola. Menu umožní začít, pokračovat, upravit základní nastavení a hru korektně ukončit. Esc a návrat do hry musí správně předávat vstup i kurzor.

Použij prostorové zvuky střelby, kroků podle povrchu, zásahů, přebíjení a prostředí. Zvukový efekt musí následovat skutečnou událost. Zastavení střelby nesmí zanechat nekonečně opakovaný zvuk a smrt nesmí ponechat aktivní krokovou smyčku. V češtině používej krátké a srozumitelné texty.

## 10. Architektura a výkon

Drž oddělené systémy postavy, zbraní, poškození, týmu, AI, zápasu, rozhraní a assetů. Pro rozšíření používej datové definice, nikoli jednu obří třídu. Herní logika běží v podporovaném runtime enginu; standardní editorový Python slouží k přípravě projektu a assetů, nikoli jako skrytá závislost živé FPS.

BluePrinty, mapy a materiály skutečně vytvářej přes ověřené dostupné rozhraní editoru nebo nástroje. Textový seznam uzlů není vytvořený Blueprint. C++ kód bez zkompilování a připojení do mapy není hratelná hra.

Výchozí výkonový cíl je **1080p a přibližně 60 FPS při sedmnácti botech**, podle skutečného hardwaru a nastavení. Je to cíl, nikoli slib nebo výsledek měření. Nejdříve hardware zjisti. Volba Lumen, Nanite, stínů, volumetrie a dalších funkcí musí odpovídat konkrétním assetům, verzi enginu a měření.

Měř CPU/GPU čas, rozpočty AI, paměť a náročné pohledy. Uveď interní rozlišení a případný upscaling. Frame generation ani dopočítané snímky nezaměňuj za rychlost základní simulace. Optimalizuj světla, instance, LOD, vzdálené animace a materiály; kvalitu blízkých rukou a zbraně udrž.

## 11. Pořadí realizace

**Fáze A — dostupnost a první spuštění.** Prověř prostředí, založ otevřitelný projekt, zprovozni vstup, postavu, základní střelbu a místní test. Graybox v této fázi je pracovní pomůcka. Zaznamenej reálné spuštění a případné blokátory.

**Fáze B — ověřený vizuální vzorek.** Dokonči jednu malou scénu s hotovým vojákem, puškou, rukama, schody, zdí a částí budovy. Proveď jeden skutečný přenos assetu z Higgsfieldu a zkontroluj import. Dolaď pohyb, kontakty, textury a měřítko před rozšiřováním mapy.

**Fáze C — kompletní herní cyklus.** Implementuj tři týmy, cíl, skóre, smrt, respawn, výsledek a restart. Nejprve několik botů, poté všech sedmnáct. Hru musí jít dohrát bez zásahu do editoru.

**Fáze D — dokončené prostředí.** Vybuduj mapu, hlavní budovy a interiéry. Přidej terén, mraky, atmosféru, zvuk a rozhraní. Nahraď viditelné provizorní assety a znovu prověř cesty AI i kolize.

**Fáze E — opravy a předání.** Projdi přílohu, oprav konkrétní selhání, změř výkon, ověř opětovné spuštění a nech dostupný místní test. Pokud je proveditelný Pixel Streaming, otestuj také tuto cestu.

Po každé fázi ulož stav a krátce napiš: co funguje, co jsi opravdu spustil, co je stále vadné a co následuje. Nepřeskakuj opravy zjevných vad jen proto, abys přidal další systém. Nevydávej pracovní blokout za finální grafiku.

## 12. Důkazy, kontinuita a dokončení

Udržuj krátký stavový dokument projektu s aktuální fází, startovací mapou, verzemi nástrojů, hotovými položkami, vadami a dalším krokem. Při pokračování po zkrácení kontextu jej přečti. Nezačínej projekt znovu a nepřepisuj dříve hotové assety bez důvodu.

U každého testu rozliš `PASS / FAIL / NOT TESTED / BLOCKED`. Pokud nemáš možnost vidět výstup, označ vizuální kontrolu jako neprovedenou. Render z Blenderu neprokazuje vzhled ve hře; test kompilace neprokazuje chování nepřátel.

V závěru sděl pouze ověřitelný stav: umístění projektu, startovací mapu, zda test opravdu běží, přesnou dostupnou adresu nebo postup spuštění, ovládání, použití Higgsfieldu, provedené zkoušky a zbývající vady. Nedoplňuj smyšlené FPS, screenshoty, videa nebo výsledky.

Celé zadání je dokončené teprve tehdy, když existuje lokálně hratelná verze, má sjednaný rozsah, prošla povinnými zkouškami a nemá blokující vady. Pokud vnější překážka brání dokončení, předlož konkrétní dosažený výsledek a přesný chybějící krok. Neoznačuj takový stav jako hotovou hru.

**Začni nyní kontrolou prostředí, přečtením přílohy a prvním skutečným spuštěním. Pokračuj realizací podle uvedených fází.**

## KONEC ZADÁNÍ PRO REALIZACI

## Ověřené podklady a jejich rozsah

Technické možnosti se mohou měnit. Odkazy slouží k ověření postupů; vždy vyber dokumentaci odpovídající nainstalované verzi. Rozměry mapy, počet botů, hodnoty režimu a limity testů jsou návrhem tohoto zadání.

- [WARDOGS na Steamu](https://store.steampowered.com/app/1867240/WARDOGS/) — oficiální popis taktické FPS a boje tří týmů; není zdrojem pravidel našeho prototypu.
- [Epic: Getting Started with Pixel Streaming](https://dev.epicgames.com/documentation/en-us/unreal-engine/getting-started-with-pixel-streaming-in-unreal-engine) — spuštění Unrealu, infrastruktury a ovládání přes prohlížeč; dokumentace uvádí také Standalone Game.
- [Epic: IK Rig Animation Retargeting](https://dev.epicgames.com/documentation/unreal-engine/ik-rig-animation-retargeting-in-unreal-engine) — přenos animací mezi kostrami.
- [Epic: Root Motion](https://dev.epicgames.com/documentation/en-us/unreal-engine/root-motion-in-unreal-engine) — vztah animace a skutečného pohybu postavy.
- [Epic: AI Perception](https://dev.epicgames.com/documentation/en-us/unreal-engine/ai-perception-in-unreal-engine) — zrak, sluch a předávání podnětů AI.
- [Epic: Scripting the Unreal Editor Using Python](https://dev.epicgames.com/documentation/unreal-engine/scripting-the-unreal-editor-using-python) — odlišení editorové automatizace od herního runtime.
- [Higgsfield](https://higgsfield.ai/) — možnosti 3D generování, riggingu, klipů a 3D Jutsu byly pro toto zadání ověřeny také přímo v připojeném katalogu nástrojů dne 26. 9. 2026. Nejde o záruku stejného připojení v jiném klientu.

