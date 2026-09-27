# Pravidla kvality a testy — IRON VALLEY

**Povinná příloha k:** `01_HLAVNI_PROMPT_UE5.md`  
**Určeno pro:** implementaci a ověřování v Claude Code / Claude Opus  
**Datum:** 26. 9. 2026

Přečti celý tento dokument před tvorbou hlavních assetů. Testy prováděj na skutečném herním výstupu, pokud konkrétní položka nevyžaduje kontrolu zdrojového modelu. Všechna číselná kritéria níže jsou **navržené cíle tohoto prototypu**, nikoli univerzální průmyslové normy, slibovaný výkon nebo již provedená měření.

## 1. Co znamená dokončená hra

Musí existovat otevřitelný Unreal projekt s uloženou startovací mapou a skutečně spuštěný místní test. Hráč musí zvládnout celý cyklus od spuštění přes hru a smrt až po výsledek a další kolo. Modely, animace, AI a prostředí musí splňovat níže uvedené podmínky.

Nevydávej za hotovou hru návrhový dokument, vygenerované obrázky, render scény, video, kompilující kód bez mapy nebo menu s nefunkčními tlačítky. Dočasná geometrie může sloužit při vývoji, ale viditelné hlavní objekty finální ukázky mají být dokončené.

### Závažnost vad

| Úroveň | Význam | Příklady | Důsledek |
| --- | --- | --- | --- |
| P0 | Zastaví použití nebo ohrožuje projektová data | Pád, nespustitelný projekt, ztráta uložené mapy | Opravit před další fází |
| P1 | Zásadně porušuje hru nebo hlavní požadavek kvality | Střelba skrz zeď, zlomené nohy, deformované FPS prsty, nefunkční respawn, skákající AI | Brání označení výsledku jako hotového |
| P2 | Viditelný nedostatek bez zničení základní funkce | Menší chyba vzdálené textury, lokální nevýrazný detail, drobný zvukový přechod | Zaznamenat; může zůstat jako známé omezení |

Opakující se malá vada, která ovládá celý herní obraz, může být P1. Označení nepoužívej ke zlehčování zjevných problémů.

Každý povinný test má jeden ze stavů `PASS`, `FAIL`, `NOT TESTED`, `BLOCKED`. Chybějící důkaz není `PASS`. Vnější blokátor může práci zastavit, ale nemění nesplněný test na úspěšný.

## 2. Jak zaznamenávat ověření

Udržuj jednoduchý soubor `QA_REPORT.md` uvnitř herního projektu. Do něj zapisuj revizi nebo stav projektu, verzi enginu, datum, hardware, startovací mapu, rozlišení, nastavení grafiky, počet botů a provedené testy. Nemusíš psát samostatný automatický test pro každý vizuální detail. Automatizuj hlavně pravidla, kde kontrola zachytí skutečnou chybu: munici, skóre, respawn a nedovolené přechody stavů.

| Pole záznamu | Co skutečně uvést |
| --- | --- |
| ID testu | Stabilní označení z tohoto dokumentu |
| Postup a podmínky | Kde, s jakým počtem botů a nastavením test proběhl |
| Výsledek | PASS / FAIL / NOT TESTED / BLOCKED |
| Důkaz | Log, naměřené hodnoty, skutečný screenshot nebo záznam hry |
| Nález a oprava | Co se pokazilo a jaká úprava to řeší |
| Opakované ověření | Jen související test po opravě a potřebná návaznost |

Převzetí nevyžaduje nekonečné opakování všech testů. Jakmile je konkrétní riziko ověřené, pokračuj. Po změně rigování ověř animace a zbraň; po změně mapy kolize a navigaci; po změně střelby zásahy a munici.

Screenshot pořizuj přímo ze hry. Video animace kontroluj v normální rychlosti i zpomaleně. V obraze pro hodnocení modelu vypni nebo omez efekty, které by zakryly vady. Pokud nemáš možnost obraz vidět, nepředstírej vizuální kontrolu.

## 3. Modely a shoda s referencí

### GEO-01 — Silueta a proporce

Pro každý hlavní model porovnej referenci a herní pohled ve srovnatelném úhlu a perspektivě. Zaměř se na proporce, délku a tloušťku částí, hlavní tvar, charakteristické detaily a materiálové rozdělení. U postavy zkontroluj hlavu vůči tělu, ramena, paže, dlaně, pánev a délky nohou.

Při shodných známých rozměrech je pracovní cíl odchylka nejvýše přibližně 5 % u hlavních proporcí. Tento limit nepoužívej tam, kde jediný perspektivní obrázek neumožňuje rozměr poctivě odhadnout; takovou nejistotu napiš a zvol věrohodnou konstrukci. Menší detail nemůže omluvit chybnou celkovou siluetu.

**PASS:** model drží vizuální identitu reference ve hře, ne jen ve zdrojovém renderu. Neznámé části jsou konzistentně doplněné a označené jako interpretace.

### GEO-02 — Geometrie, UV a export

Prověř nechtěné díry, obrácené normály, zdvojené plochy, prosvítání, rozbité tangenty, natažené UV a nekonzistentní měřítko. Prohlédni model ze všech stran a v místech ohybů. U deformované postavy zkontroluj geometrii také v krajních pózách.

Ověř jednotky a osy na testovacím metru a na výšce člověka. Zkontroluj pivot, materiálové sloty, správné připojení textur, oddělení pohyblivých částí a opakovaný import bez duplikátů. Zachovej upravitelný zdroj.

**PASS:** export odpovídá zdroji v rozsahu podporovaných funkcí; všechny odlišnosti jsou vědomě opravené nebo zdokumentované. Úspěšný exportní log sám o sobě nestačí.

### GEO-03 — Optimalizace bez ztráty vzhledu

Sleduj skutečný obraz z herní kamery. Vzdálené úrovně detailu musí přecházet bez nápadného měnění tvaru, okna nemají náhle mizet a zbraň hráče nesmí v blízkosti přepnout na hrubou siluetu. Počet polygonů není samostatný důkaz kvality.

Začni rozumnými texturami podle objektu; vyšší rozlišení dej místům viditelným zblízka. Nedávej automaticky 8K každé rekvizitě. Omezování detailu nesmí sloužit jako omluva pro nahrazení hotové pušky kvádrem nebo domu neprůchozí krabicí.

## 4. Ruce, prsty a držení zbraně

### HAND-01 — Anatomie

Zkontroluj obě ruce bez zbraně v otevřené, sevřené a přechodové póze. Každá má pět prstů, správný palec, přirozenou orientaci kloubů a stabilní délku článků. Ukaž alespoň pohled na dlaň, hřbet a bok.

Ověř váhy kolem kloubů, zápěstí a přechodu ruky do předloktí. Při ohnutí nesmí vznikat ostré zborcení, propad objemu, záměna prstů ani natahování článků. Rukavice tento test absolvují stejně jako holá ruka.

**FAIL/P1:** prst navíc, chybějící prst na viditelné ruce, srůst, obrácený kloub, nápadná deformace nebo neustálé pronikání prstů do zbraně.

### HAND-02 — Kontakt se zbraní

Prohlédni idle, chůzi, sprint, ADS, výstřel a obě varianty přebíjení. Kontroluj palec, rukojeť, lučík, podpůrnou dlaň, předpažbí, zásobník a návaznost rukou na ramena.

Kontakt je stabilní při změně směru a při recoil. Ruka držící předmět se nesmí zpožďovat o několik snímků. IK podpůrné ruky se během přebíjení uvolňuje řízeně a znovu se plynule zapíná; nesmí současně přetahovat ruku s přebíjecí animací.

**PASS:** v normální rychlosti ani při prohlížení klíčových snímků nejsou zjevné mezery, průniky, vykloubená zápěstí nebo nesmyslný úchop.

### HAND-03 — Kamera a viditelnost

Otestuj nízkou a vysokou povolenou hodnotu FOV, pohled nahoru a dolů, stěnu těsně před hráčem, dřep a návrat z menu. Zkontroluj, že se neobjeví druhá kopie paží, vnitřek hlavy, neúplný rukáv nebo oddělená ruka. Samostatný FPS model a světový model se musí zobrazovat ve správném kontextu.

## 5. Chůze, nohy a přechody animací

Pro vývoj vytvoř malý interní zkušební prostor: rovina, mírný svah, strmější povolený svah, schody, práh, nízký strop, úzké dveře a malý sráz. Nemusí být součástí mapy pro hráče.

### ANIM-01 — Přiměřený krok

Pozoruj člověka ze strany a zepředu při chůzi, běhu a sprintu. Sleduj délku kroku, tempo, zrychlení, zastavení a přenos váhy. Jako počáteční ladění můžeš použít chůzi přibližně 1,4–1,8 m/s, běh 3–4 m/s a krátký sprint 5–6,5 m/s; hodnoty přizpůsob postavě a hernímu tempu.

Tyto rychlosti nejsou náhradou odpovídajících klipů. Krátký cyklus chůze extrémně zrychlený nebo natažený na sprint neprojde. Dva systémy nesmějí zároveň přičítat posun těla. Pětimetrový krok, viditelný teleport nebo reset postavy na začátek cyklu je P1.

### ANIM-02 — Kontakt se zemí

Ověř oporu chodidla na rovině, schodech a svazích. Pracovní cíl v úsecích pevné opory je skluz do přibližně 3 cm a průnik podrážky do tvrdého povrchu do přibližně 2 cm. Měř záměrně vybrané kontaktní intervaly; přirozené odvalení, otočení na špičce a pohyb ve vzduchu nevyhodnocuj jako stoj na místě.

Především nesmí být pouhým okem vidět soustavné bruslení, plavání nad terénem nebo propadávání chodidla. IK přenáší potřebnou korekci na pánev a respektuje dosah končetin. Cíle mimo dosah nesmějí roztahovat kostru.

### ANIM-03 — Kolena a délky kostí

Na běžných lokomočních klipech zkontroluj stabilitu délky stehenní a holenní části. Výchozí cíl je žádné záměrné škálování těchto kostí; technická odchylka nad přibližně 2 % potřebuje vysvětlení a vizuální kontrolu. Koleno má ohyb ve správném směru, stabilní orientaci a nepřeskakuje mezi řešeními IK.

**FAIL/P1:** obrácená kolena, vykloubené kotníky, natahování nohy na další patro, zhroucená pánev nebo prudké praskání pózy při každém kroku.

### ANIM-04 — Přechody a snímková frekvence

Ověř alespoň: idle → chůze → běh → zastavení, dopředný pohyb → strafe → pohyb vzad, stoj ↔ dřep, otočení o 90° a 180°, pád → dopad → pohyb, běh → ADS a přebití → přerušení → návrat.

Prohlédni výsledek při 30, 60 a vyšší dostupné snímkové frekvenci. Pokud hardware 120 FPS nedosáhne, netvrď, že tato varianta prošla. Pohyb, délka přebití a palebný interval nemají měnit význam s FPS. Zpomalený záznam pomáhá najít chybu, rozhodující je i přirozenost v normální rychlosti.

## 6. Zbraň, munice a zásahy

### GUN-01 — Obsluha a účet munice

Otestuj střelbu z plného zásobníku, poslední náboj, prázdný zásobník, přebití částečného zásobníku, přebití z prázdna a přebití při nedostatku rezervy. Přerušení vyzkoušej před výměnou zásobníku i po ní.

Definuj, zda systém eviduje náboj v komoře samostatně. Součet munice v zásobníku, případné komoře a rezervě musí odpovídat počátečnímu stavu, výstřelům, doplnění a případné výslovně implementované ztrátě. Žádný přechod nesmí vytvářet munici navíc. Při respawnu resetuj stav přebití i model zásobníku.

Pro kritické události použij autoritativní herní stav a jednorázové přechody. Animační událost nesmí při opakování přidat munici podruhé. Logicky hotové přebití musí odpovídat okamžiku, kdy je zbraň vizuálně připravená.

### GUN-02 — Překážka před ústím

Zkus střelbu těsně u stěny, za rohem, přes okno a přes nízký kryt. Opakuj ve stoje i v dřepu. Kamera může vidět cíl, ale ústí může být blokované. V takové situaci zásah nesmí projít stěnou.

Zkontroluj, že stejná pravidla platí pro boty a že muzzle flash, trajektorie nebo stopa zásahu nepřicházejí z jiného místa. Penetraci materiálů povol pouze tehdy, pokud je výslovně implementovaná a testovaná; není vysvětlením náhodného průstřelu zdí.

### GUN-03 — Recoil a přechody

Střílej jednotlivě i dávkou při různých FPS a během pohybu. Zkontroluj rychlost palby, počet zásahů, návrat recoil, zvukové vrstvy, ADS a opuštění ADS. Po otevření menu nebo smrti nesmí pokračovat vstup pro palbu. Mířidla musí odpovídat pravidlům zásahu, která hra skutečně používá.

## 7. AI a navigace

### AI-01 — Zrak, sluch a paměť

Připrav oddělené situace: viditelný hráč, hráč za neprůhlednou zdí bez zvuku, hráč vydávající zvuk za zdí a hráč, který po ztrátě vizuálního kontaktu změní směr. Sleduj debug stav vnímání, poslední známou pozici a rozhodnutí.

Bot může reagovat na zvuk nebo zásah, ale nesmí tím získat trvalé přesné sledování skrytého hráče. Po ztrátě kontaktu nemá dál přepisovat cíl skutečnou aktuální pozicí hráče bez nového podnětu. Prověř také zapomenutí mrtvého nebo respawnovaného cíle.

### AI-02 — Cesty a vzájemné vyhýbání

Pusť všech sedmnáct botů přes hlavní směry mapy, dveře, schody, úzké cesty a okolí kontrolního bodu. U používaných dveří ověř konzistenci jejich stavu s navigací. Bot musí buď umět projít, otevřít dveře, nebo zvolit jinou trasu.

Při úmyslném zablokování cesta selže čitelně a AI hledá jiné řešení. Výchozí cíl je rozpoznat neúspěšný přesun během přibližně 2–3 sekund a zahájit obnovu. To není limit pro čekání v krytu ani jiné záměrné stání.

Žádný bot se nesmí opakovaně bez výstupu zaseknout v pohybu na jednom místě nebo být teleportován před hráčem. Přístupné kryty nesmějí více botům současně přidělit tutéž pozici bez řešení konfliktu.

### AI-03 — Bojové chování

Pozoruj reakci na cíl, natočení, zamíření, krytí, palbu, přebití a změnu pozice. Reakční čas musí být nenulový a datově nastavitelný. Zvolenou prodlevu a nepřesnost ověř měřením; nevkládej jen náhodnost do každého snímku.

Bot dodržuje zásobník, frekvenci střelby, kolize a existenci krytu. Hlaveň při palbě nemíří do země, zatímco zásahy létají na hráče. Nesmí okamžitě zamířit přes záda nebo střílet se zbraní mimo ruce během přebití.

### AI-04 — Tým a cíl

Nech kolo chvíli běžet bez zásahu hráče. Všechny tři týmy se musí smysluplně přesouvat k aktivní oblasti a bojovat mezi sebou. Spojenci nesmějí hráče automaticky označit za nepřítele. Nastavení friendly fire musí být jednoznačné; pro první verzi může být vypnuté.

Ověř přepočet úkolů po smrti, změně kontroly oblasti a restartu kola. Všichni boti nemají donekonečna lovit hráče a ignorovat cíl zápasu.

## 8. Fyzika a kolize

### PHY-01 — Pohyb hráče

Projdi schody s běžnými výškami stupňů, práh, svah pod limitem a svah nad limitem. Vyzkoušej diagonální běh proti rohu a průchod dveřmi. Změř, že diagonální pohyb nemá nechtěnou výhodu v rychlosti.

V dřepu zajeď pod nízký strop a zkus vstát. Postava smí vstát až při dostatečném prostoru. Maximální krok musí být explicitně nastavený a odpovídat mapě; metr vysoká zeď nesmí být náhodně vyhodnocená jako běžný schod.

Prověř pád, dopad a návrat řízení. Žádné pronikání pod terén, vystřelení postavy z rohu nebo změna tělesného měřítka při změně postoje.

### PHY-02 — Smrt a ragdoll

Vyzkoušej alespoň deset úmrtí v různých situacích: rovina, schody, svah, blízkost stěny a kontakt více postav. Ragdoll musí převzít pózu bez prudkého skoku a tělo má zůstat stabilní.

Po smrti se vypne bojové rozhodování, vstup postavy, střelba a nevhodné animace. Kolizní nastavení kapsle a ragdollu si nesmějí odporovat. Impuls po zásahu nevyhodí tělo přes mapu. Úklid starých těl uvolní zdroje a nepoškodí respawn.

### PHY-03 — Dveře a dynamické předměty

Ověř kontakt s dveřmi při otevírání, zavírání a průchodu dvou postav. Malé dynamické předměty se nesmějí bez konce třást, propadat podlahou nebo blokovat každou cestu. Pokud rychlý pohyb vyžaduje detekci průchodu mezi snímky, zvol příslušné řešení a otestuj ho na problematickém předmětu.

## 9. Budovy, krajina, světlo a zvuk

### ENV-01 — Uvěřitelné domy

Prohlédni hlavní budovy z blízka, šikmo a zevnitř. Zkontroluj tloušťku otvorů, rámy, prahy, schody, přesah střechy, návaznost podlah a terénu. Funkční interiér má odpovídat vnějším rozměrům. Hráč se nesmí dívat skrz zadní stranu jediné roviny, která předstírá zeď.

Požadované jsou tři odlišné hlavní typy budov a alespoň dva průchozí interiéry. Vnější dekorace nesmí skrývat neexistující vnitřní místnost, kterou hra vybízí použít. Zkontroluj kolize dveří a oken pro pohyb i střelbu.

### ENV-02 — Povrchy a textury

Pozoruj zbraň, vojáka, fasádu, podlahu a terén na přímém světle i ve stínu. Hledej rozmazané hlavní textury, nesprávné kanály, přehnaný lesk, švy, opakující se vzor a příliš odlišnou hustotu detailů vedle sebe.

Materiál musí být rozpoznatelný i bez přemrštěného barevného filtru. Zkontroluj načítání mipů a texturovou paměť při rychlém otočení kamery. Chybějící textura, růžový materiál nebo prázdný povrch hlavního objektu je P1.

### ENV-03 — Krajina a kontakt se zemí

Projdi cestu od spawnů do oblasti všemi hlavními trasami. Prověř plovoucí stromy, zanořené dveře, visící kameny, neprůchozí drobnou vegetaci, ostré zlomy terénu a nečekané díry v kolizi. Herní hranici začleň do prostředí a vysvětli ji hráči.

### ENV-04 — Mraky, obloha a expozice

Sleduj oblohu při klidu i rychlém otočení kamery. Prověř časové rozpadání mraků, blikání stínů, výrazné pruhování, přepálený horizont a nesoulad slunce se stíny. Zkontroluj výhled z okna a přechod ven/dovnitř.

Mraky mohou být podle výkonu jednodušší, ale mají zachovat věrohodnou hloubku a světlo. Stálé denní nastavení je v první verzi v pořádku. Filmové efekty nesmějí snížit čitelnost nepřátel nebo zakrýt špatně zpracovanou geometrii.

### SND-01 — Zvukové události

Kroky odpovídají kontaktu chodidel a povrchu. Přebití, střelba a zásahy mají správný okamžik. Ověř prostorový směr zvuku, útlum vzdálenosti a ukončení smyček při smrti, pauze a restartu. Chybějící kvalitní zvukový asset pojmenuj; nevydávej nesouvisející provizorní zvuk za finální.

## 10. Pravidla kola a uživatelské rozhraní

### GAME-01 — Skóre oblasti

Ověř prázdnou oblast, jednoho přítomného, početní převahu, shodu dvou týmů, shodu tří týmů, smrt uvnitř a rychlý vstup/výstup. Body dostává jen tým s jednoznačnou převahou živých členů podle pravidel v hlavním souboru.

Ověř konec při dosažení skóre, časový limit, remízu a vynulování stavu. Zbytky timerů z předchozího kola nesmějí bodovat v novém.

### GAME-02 — Respawn a celé kolo

Proveď nejméně tři smrti hráče a jedno kompletní kolo. Respawn obnoví zdraví, výbavu, kameru, ovládání, viditelnost a správné napojení modelu. Hra musí jít znovu spustit z výsledkové obrazovky bez otevření editoru.

### UI-01 — Ovládání a čitelnost

Vyzkoušej menu, pauzu, změnu citlivosti, dostupné FOV, návrat do hry a ukončení. Kurzorem ani zachycením myši nesmí být hráč uvězněn. HUD musí ukazovat skutečný stav, nikoli pevná ukázková čísla. Text nesmí přetékat při 1080p a přiměřeném škálování rozhraní.

## 11. Výkon, opakovatelnost a spuštění

### PERF-01 — Reprezentativní měření

Po úvodním zahřátí shaderů zaznamenej alespoň tři minuty skutečné hry se sedmnácti boty. Projdi interiér, otevřený výhled, střelbu a kontrolní bod s více postavami. Jednorázovou přípravu shaderů zaznamenej odděleně; její dopad na první spuštění nezamlčuj.

Uveď CPU, GPU, RAM, rozlišení, interní renderovací rozlišení, preset a případný upscaling. Zapiš průměrné FPS a alespoň 95. percentil času snímku, případně i 99. percentil. Zaznamenej samostatné CPU/GPU časy, pokud jsou dostupné.

Výchozí cíl je průměr okolo 60 FPS nebo vyšší při 1080p a 95. percentil času snímku přibližně do 25 ms na zjištěném cílovém stroji. Pokud není dosažitelný, uveď naměřené hodnoty a konkrétní úpravy. Nesmíš napsat „optimalizováno na 60 FPS“ pouze na základě odhadu.

Po snížení počtu botů, rozlišení nebo nároků grafiky označ výsledek jako jinou konfiguraci. Pokud nemáš cílový počítač k dispozici, výkon na něm je `NOT TESTED`. Klesající FPS při opakovaných kolech nebo rostoucí počet aktivních těl je důvod prověřit správu zdrojů.

### RUN-01 — Opětovné otevření

Ulož projekt, ukonči svou testovací instanci a znovu jej otevři běžným postupem. Ověř načtení mapy, assetů, ovládání, shaderů a start zápasu. Projekt nesmí záviset na neuloženém objektu v editoru nebo na dočasném adresáři, který při restartu zmizí.

Zkontroluj, že runtime nepotřebuje editorový Python k běžné střelbě nebo AI. V readme projektu uveď potřebné verze a přesný postup spuštění. Nevydávej nevyzkoušený příkaz za ověřený start.

### RUN-02 — Prohlížečová varianta, pokud byla připravena

Ověř běžící Unreal aplikaci, spojení se streamovací infrastrukturou a příjem obrazu i zvuku. Z prohlížeče vyzkoušej myš, chůzi, střelbu, menu, návrat ze ztráty fokusu a opětovné připojení. Uveď skutečnou adresu a stroj, na kterém funguje.

Pokud stream nefunguje, označ tento test jako `FAIL` nebo `BLOCKED` a ponech funkční nativní test. Tato položka je podmíněná technickou proveditelností; nenahrazuje povinné místní spuštění. Video přehrávač bez možnosti ovládat hru tento test nesplňuje.

## 12. Kontrola zapojení Higgsfieldu

### HF-01 — Skutečný přínos do herního projektu

V manifestu dolož alespoň jeden model nebo animační podklad získaný přes dostupné nástroje Higgsfieldu a skutečně použitý při výrobě herního assetu. Uveď postup od vstupu přes opravy po konkrétní objekt nebo klip v Unrealu.

Pokud šlo o video jako referenci, popiš jeho skutečné převedení do ručně upravené nebo jinak vytvořené kosterní animace. Neoznačuj samotné video jako herní animační klip. Pokud šlo o automatický rig, dolož jeho kontrolu a potřebné opravy.

Ověř, že používáš skutečně podporovanou cestu exportu/importu. Nepřenášej domnělou podporu z jiného rozhraní a neuváděj úspěch jen podle dokončené generace. Chybějící integrace je `BLOCKED`, nikoli skrytá výjimka z požadavku.

## 13. Závěrečné převzetí

Před označením projektu za hotový musí být splněno:

- Otevřitelný projekt a skutečně ověřené místní spuštění.
- Kompletní kolo se třemi týmy, hráčem a sedmnácti boty.
- Jedna dokončená mapa, požadované hlavní budovy a dva průchozí interiéry.
- Hotová puška, funkční pistole a odpovídající animace jejich použití.
- Přirozené ruce, prsty, chůze, kolena a kontakty s terénem.
- Funkční zásahy, munice, respawn, AI, kolize a stabilní ragdoll.
- Konzistentní textury, atmosféra, obloha, mraky, světlo a zvuk.
- Skutečné doložené využití Higgsfieldu.
- Provedené povinné testy, žádné otevřené P0/P1 a uvedené známé P2.
- Poctivý výkonový report; žádná neověřená tvrzení o cílovém hardwaru.

Finální zpráva pro uživatele má být krátká a konkrétní: co může hrát, kde a jak to spustí, základní ovládání, co bylo otestováno a co ještě chybí. Když něco brání dokončení, uvedení přesné překážky je správný výsledek reportu; není to důvod vymyslet úspěšný test.

**Rozhodující je kvalita skutečné hry v pohybu. Hezký obrázek, komplikovaný kód ani úspěšná generace samy o sobě tento standard nesplňují.**

