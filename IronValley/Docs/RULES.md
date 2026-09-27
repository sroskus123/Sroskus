# IRON VALLEY — pravidla hry a jejich jádro

Tento dokument popisuje **přesná pravidla** kontrolního bodu, kola, respawnu a zbraní (munice, kadence, přebití)
a všechna rozhodnutí, která zadání (§2.1, GAME-01, GAME-02, GUN-01) nechávalo otevřená. Pravidla existují jako
čisté jádro dvakrát (rozhodnutí D6 v `Docs/ARCHITECTURE.md`) a obě implementace procházejí stejnými testovacími vektory.

| Část | Umístění |
| --- | --- |
| JS jádro (prohlížečová verze) | `Web/src/core/` — ES moduly bez three.js a bez DOM |
| C++17 jádro (pro modul UE5) | `Core/` — knihovna `ironvalley_core` bez výjimek, bez RTTI, bez závislostí |
| Načítání JSON v C++ (testy, nástroje) | `Core/json/` — `ironvalley_core_json` (vendorovaný nlohmann/json 3.11.3, MIT, `Core/third_party/nlohmann/`) |
| Laditelné hodnoty | `Shared/config/rules.json` |
| Sdílené testovací vektory | `Shared/testvectors/*.json` (formát: `Shared/testvectors/README.md`) |
| JS testy | `Web/tests/unit/core_*.test.mjs` |
| C++ testy | `Core/tests/` (registrované v `ctest`) |

C++ jádro je přeložené a otestované jen jako samostatná knihovna na Linuxu (GCC 13, clang 18). V Unreal Engine **nebylo spuštěno**
(UE v tomto prostředí není) — to je NOT TESTED.

## Jak ověřit

```bash
# JS (Node 22, bez npm závislostí)
cd IronValley/Web
node --test tests/unit/core_*.test.mjs

# C++ (CMake + ctest)
cd IronValley
cmake -S Core -B Core/build -DCMAKE_BUILD_TYPE=Release
cmake --build Core/build -j4
ctest --test-dir Core/build --output-on-failure

# C++ s AddressSanitizer + UBSan (use-after-free, přetečení, nedefinované chování)
cmake -S Core -B Core/build-asan -DCMAKE_BUILD_TYPE=Debug -DIV_SANITIZE=ON
cmake --build Core/build-asan -j4
ctest --test-dir Core/build-asan --output-on-failure

# nezávislá kontrola hodnot závislých na semeni (Python 3, bez JS i C++ jádra; ctest ji spouští jako seed_reference)
python3 Shared/testvectors/tools/seed_reference.py

# po změně JS jádra, která mění chování: znovu vygenerovat fuzz vektory (C++ je pak musí reprodukovat)
cd IronValley/Web
node tests/unit/support/generate_fuzz_vectors.mjs          # zapíše Shared/testvectors/fuzz_*.json
node tests/unit/support/generate_fuzz_vectors.mjs --check  # jen ověří, že uložené soubory nejsou zastaralé
```

## 1. Čas a tiky

- Jádro počítá čas v **celých mikrosekundách** (JS `Number` do 2^53, C++ `int64_t`). Konfigurace je v sekundách;
  převod `secondsToMicros(s) = Math.round(s · 10^6)` (C++ má stejné zaokrouhlení, polovina směrem k +∞).
- Důvod: součet libovolného rozdělení stejného intervalu na tiky je přesný, takže počet výstřelů, body, respawny i konec kola
  **nezávisí na délce snímku** a JS i C++ dávají bit po bitu totéž. Platí to i pro respawn uprostřed tiku: pokusy o spawn
  proběhnou v přesných okamžicích a `Match` tik v těchto okamžicích dělí (oddíl 7), a rezervace bodu spawnu se měří časem
  jádra, ne hranicemi `update` (oddíl 5), takže nezávislý je i výběr bodu. Jediný předpoklad: vstupy světa (kdo je
  v oblasti, polohy těl a výsledek predikátu spawnu, spoušť) jsou po dobu jednoho tiku konstantní — jemnější tik je prostě
  vzorkuje častěji. Engine, který predikátu předá nově spawnuté tělo až v dalším tiku, tak při jemném tiku může bod
  po skončení rezervace odmítnout dřív než při hrubém; to je změna vstupu světa, ne pravidel.
- Engine převádí svůj plovoucí `dt` pomocí `TickClock` (zaokrouhluje celkový čas, ne jednotlivé kroky → žádný drift).
  Architektura počítá s pevným krokem 1/60 s; jádro ale funguje pro jakýkoli krok včetně nulového.
- Tik `[t, t+dt]` má dvě pravidla, obě nezávislá na rozdělení času:
  - **Milníky akcí a body** (vložení zásobníku, uvolnění závěru, nabití, konec akce, bod za kontrolu, konec kola)
    naplánované na čas ≤ t+dt proběhnou v tomto tiku (uzavřený interval). Snímek stavu v čase T tedy obsahuje vše,
    co bylo naplánováno na ≤ T.
  - **Výstřely** pokrývají polootevřený interval `[t, t+dt)`: výstřel přesně v čase t+dt patří dalšímu tiku, kde se znovu
    čte spoušť. 600 ran/min držených přesně 1 s = 10 výstřelů; 750 ran/min 1 s = 13 výstřelů.
- Záporné, neceločíselné (JS) nebo větší než 2^53 − 1 µs `dt` (JS `Number.isSafeInteger`, C++ `validDt` / `kMaxDtUs`) je
  chyba volajícího. JS vyhodí `RangeError`. C++ jádro nepoužívá výjimky, takový tik proto **neprovede vůbec** (stav se
  nezmění, ani se znovu nevyhodnotí oblast): `Round::tick`, `ZoneScoring::tick` a `Match::update` vrátí
  `InputResult::InvalidDt` (`"invalid_dt"`), `ZoneScoring::advance` vrátí `{0, 0}`, `WeaponState::update` vrátí 0 výstřelů,
  `RespawnSystem::update`/`advance` nic neudělají, `TickClock::advance` vrátí 0 (jen záporné dt). Díky horní mezi
  žádný mezisoučet jádra nepřeteče `int64`.

## 2. Konfigurace (`Shared/config/rules.json`)

| Klíč | Hodnota | Význam |
| --- | --- | --- |
| `teams.count` / `teams.size` | 3 / 6 | tři týmy po šesti |
| `round.preRoundDuration` | 5,0 s | odpočet před kolem |
| `round.timeLimit` | 600 s | délka kola |
| `round.scoreTarget` | 100 | cílové skóre |
| `zone.pointInterval` / `zone.pointsPerAward` | 2,0 s / 1 | 1 bod za 2 s platné kontroly |
| `zone.locations` | 3 položky | tři umístění oblasti (id + název; geometrii dodá mapa pod stejným id) |
| `respawn.delay` | 5,0 s | prodleva respawnu |
| `respawn.retryInterval` | 0,5 s | opakování pokusu, když není bezpečný bod |
| `respawn.minEnemyDistance` | 25 m | minimální vzdálenost spawnu od živého nepřítele |
| `respawn.bodyClearance` | 1 m | minimální vzdálenost spawnu od jakéhokoli živého těla |
| `combat.maxHealth` / `combat.friendlyFire` | 100 / false | zdraví, friendly fire vypnutý |
| `loadout.default` | `rifle_iv7`, `pistol_p9` | výchozí výbava |
| `weapons.rifle_iv7` | 30+1, rezerva 90 (max 180), 750 ran/min, auto/semi | puška |
| `weapons.pistol_p9` | 15+1, rezerva 45 (max 90), 450 ran/min, semi | pistole |

Časy přebití (s): puška taktické 2,2 (vložení 1,3), z prázdna 2,9 (vložení 1,3, uvolnění závěru 2,3), nabití 0,8 (commit 0,5);
pistole taktické 1,7 (0,95), z prázdna 2,1 (0,95, 1,55), nabití 0,6 (0,35). `damage` je zatím jen údaj pro systém zásahů,
jádro ho nepoužívá (poškození dostává jako celé číslo).

Kontrola konfigurace (JS `compileRules`, C++ `rulesFromJson` + `validateRules`) odmítne chybějící klíče, špatné typy
(celé číslo smí být zapsané i jako `30.0`), hodnoty mimo rozsah, `insertCommit > duration`, `boltRelease` mimo
`[insertCommit, duration]`, neznámé nebo duplicitní režimy palby, výchozí režim mimo seznam, neznámé zbraně ve výbavě,
duplicitní id atd. Neznámé klíče se ignorují (dopředná kompatibilita). Přepisy pravidel v testech jsou JSON Merge Patch
(RFC 7386: objekty se slučují, `null` klíč odstraní).

**Pravidla v C++ bez JSON vrstvy (engine UE je sestaví vlastním parserem):** `ZoneScoring`, `Round`, `RespawnSystem`
a `Match` volají `validateRules` už v konstruktoru, `WeaponState` kontroluje svou definici (`validateWeaponDef`).
Neplatná pravidla (např. výchozí `Rules{}`, `pointInterval` 0, `retryInterval` 0) nic neshodí ani nezablokují:
`configError()` vrátí první chybu, `tick`/`update`/`evaluate` vrací `InputResult::InvalidConfig` (`"invalid_config"`),
`addParticipant` `AddResult::InvalidConfig`, `start()` `false`, `Round::zoneId()` prázdný text a stav se nemění; zbraň
s neplatnou definicí je netečná (`update` 0 výstřelů, `reload` `rejected_disabled`, `resupply` −1, `enabled()` `false`).
`validateRules` navíc omezuje časy kola, oblasti a respawnu na nejvýše 86 400 s (stejně jako JS `compileRules`).
JS třídy dostávají pravidla vždy z `compileRules`, který neplatná pravidla odmítne výjimkou.

## 3. Kontrolní oblast

- Každý tik dostane seznam účastníků `{id, team, alive, active, inZone}`. **Počítá se jen `alive && active && inZone`.**
  Mrtví, respawnující (`alive = false`) i neaktivní (`active = false`, např. menu/AFK/divák) se nepočítají nikdy.
- Kontrolor = tým s **jednoznačně největším** počtem. Shoda nejvyšších (2 nebo 3 týmy) = `contested`, kontrolor žádný,
  bodování stojí. Prázdná oblast = `empty`, nic se neboduje. Shoda jen mezi nižšími týmy nevadí (2:1:1 → kontroluje tým s 2).
- Postup k dalšímu bodu patří **jen aktuálnímu kontrolorovi**. Při každé změně kontrolora, i na „nikdo“ (shoda / prázdno),
  se postup vynuluje. Předchozí vlastník tak nikdy nezíská bod z rozpracovaného postupu (ani po krátkém sporu nebo
  opuštění oblasti na jediný snímek). Změna složení stejného týmu (přijde/odejde spoluhráč, tým dál vede) postup nenuluje.
- Za každých `pointInterval` nepřetržité platné kontroly dostane kontrolor `pointsPerAward` bodů; jeden dlouhý tik může
  udělit více bodů. Skóre jsou celá čísla, v obou jádrech přesná (C++ `int64`, JS `Number`) až do **2^53 − 1**, kde se
  zastaví (saturace, JS `MAX_SCORE`, C++ `ZoneScoring::kMaxScore`). Kolo končí cílem nejvýše 1 000 000, takže herní cesta
  saturace nedosáhne; týká se jen samostatného `ZoneScoring` s extrémní konfigurací.
- Neplatný vstup (prázdné id, tým mimo rozsah, duplicitní id) tik odmítne kódem `invalid_id` / `invalid_team` /
  `duplicate_id` a **stav se nezmění**.

## 4. Kolo

Stavy `pre_round → running → ended`, `reset()` vrací do `pre_round`.

- **pre_round:** odpočet `preRoundDuration`; oblast se nevyhodnocuje a neboduje. Po doběhnutí odpočtu se zbytek téhož tiku
  už počítá jako `running` (nezávislost na délce tiku). `start()` odpočet přeskočí.
- **running:** tik vyhodnotí oblast a přičte body. Konec nastane:
  - dosažením `scoreTarget` — tým vyhrává okamžitě; čas kola se zastaví **přesně v okamžiku** posledního bodu, i uprostřed tiku;
  - vypršením `timeLimit` — vyhrává nejvyšší skóre; shoda nejvyšších skóre (včetně 0:0:0) = **remíza**.
  - Bod dokončený přesně v čase limitu se započítá; pokud jím tým dosáhne cíle, konec je `score_target` (cíl má přednost).
- **ended:** další tiky nic nemění (skóre, čas i respawny zamrznou); zabití a poškození jsou odmítnuta (`round_ended`).
  Ze stavu `ended` vede jen `reset()` (výsledková obrazovka → nové kolo).
- **reset():** vynuluje skóre, postup oblasti, odpočet, uplynulý čas, vítěze a důvod konce; ve fasádě `Match` navíc všechny
  odpočty respawnu, stav zbraní a čítače účastníků. Nic z předchozího kola nemůže v novém bodovat ani „vystřelit“ časovač.
- **Aktivní oblast:** při vytvoření kola a při každém `reset()` se vybere jedna ze tří konfigurovaných oblastí jako
  `rng.pickIndex(3)` z deterministického generátoru se semenem zápasu (každé kolo další číslo téže posloupnosti).
  Stejná oblast se smí opakovat. Během kola se oblast nemění.

## 5. Respawn

Stavy účastníka: `alive → dead → respawning → alive`.

- **Rozhodnutí o stavech:** `dead` trvá od smrti po dobu `respawn.delay` (odpočet pro HUD), `respawning` znamená
  „odpočet doběhl, čekám na bezpečný bod“. Pokud je bod hned k dispozici (běžný případ), přechod `dead → respawning → alive`
  proběhne v jednom tiku. Nový účastník a všichni po `reset` začínají v `respawning` s okamžitým pokusem.
- Pokus o spawn proběhne v **přesném okamžiku**, kdy odpočet `delay` (stav `dead`) nebo `retryInterval` (stav `respawning`)
  klesne na 0, i uprostřed dlouhého tiku; v jednom `update` tak může proběhnout i několik opakovaných pokusů. Výsledek
  nezávisí na rozdělení času na tiky. Predikát a polohy těl platí po celý `update`.
- **Výběr bodu:** kandidáti týmové spawnové oblasti se zamíchají (Fisher–Yates, deterministický generátor se semenem
  `seed XOR 0x9E3779B9`), vybere se první kandidát, který projde predikátem enginu. Predikát kontroluje volno od těl,
  kolizi s geometrií a viditelnost živými nepřáteli (raycast v enginu). Jádro poskytuje referenční vzdálenostní část
  `spawnPointSafe`: živý nepřítel blíže než `minEnemyDistance` nebo jakékoli živé tělo blíže než `bodyClearance`
  bod vylučuje (3D vzdálenost, ostrá nerovnost — přesně 25 m je bezpečné; mrtvá těla se ignorují).
- **Rezervace bodu:** bod použitý pro spawn je rezervovaný po dobu `respawn.retryInterval` (výchozí 0,5 s) **času jádra**
  a během ní se nikomu nenabídne (ani stejnému účastníkovi). Rezervace klesá s časem stejně jako odpočty, přes hranice
  `update` i úseků `Match`; bod je volný přesně v okamžiku, kdy zbývá 0. Délka = `retryInterval`, takže spoluhráč odmítnutý
  kvůli rezervaci to zkusí znovu přesně ve chvíli, kdy skončí. Důvod: engine předá predikátu polohu nově spawnutého těla
  až v dalším tiku, takže bez rezervace by dva účastníci ve stejném tiku skončili na jednom bodě; rezervace omezená na
  jeden `update` (dřívější pravidlo) ale závisela na délce tiku (jeden dlouhý tik bod blokoval déle než mnoho krátkých).
  Po skončení rezervace rozhoduje predikát (volno od těl). Účastníci se stejným okamžikem pokusu se zpracují v pořadí
  přidání. `resetRound` rezervace zruší; snímek je ukazuje jako `reservedUs[tým][index]`.
- **Když žádný bod neprojde, nespawnuje se do nebezpečí:** stav zůstane `respawning`, další pokus za `retryInterval`.
- **Spawn obnoví** plné zdraví, výchozí výbavu (každá zbraň `resetToLoadout`: plný zásobník, nabitá komora, výchozí
  rezerva, zrušené přebíjení, vynulované čítače) a odebere zbraním výbavy **zámek života**. Zámky vstupu enginu (menu,
  výsledky …) spawn nemění: hráč, který má při respawnu otevřené menu, nestřílí, dokud ho nezavře (oddíl 6).
- **Platnost referencí na zbraně:** reference (JS) i ukazatel `WeaponState*` (C++) získaný přes `weapon(id, zbraň)` platí
  po celou dobu života `RespawnSystem`/`Match`. Respawn i reset kola objekt jen resetují na místě, přidání dalších účastníků
  ho nepřesune a zbraň odebraná z výbavy (`setLoadout`, projeví se při dalším spawnu) se nezruší, jen zůstane vypnutá; po
  opětovném vybavení je to tentýž objekt. V C++ leží objekty na haldě v `Participant::armory`, `Participant::weapons` na ně
  jen ukazuje. Ukazatel na samotný `Participant` v C++ platí jen do dalšího `addParticipant`.
- **Smrt** nastaví zbraním **zámek života** (přeruší přebíjení/nabíjení s důvodem `death` podle pravidel přerušení níže,
  zruší platný stisk) a spustí odpočet. Zámek života drží jen `RespawnSystem`: je nastavený po celou dobu, kdy účastník
  není `alive` (i ve stavu `respawning` po přidání nebo po resetu kola, tam s důvodem přerušení `other`), a na zbraních
  mimo výbavu. Veřejným API ho nejde odebrat (JS: klíč je symbol, který `index.js` neexportuje; C++: soukromá metoda
  pro `RespawnSystem`). Mrtvý proto nestřílí ani nepřebíjí, ať engine volá `enable` s jakýmkoli důvodem (GUN-03, oddíl 6).
- **Zámky vstupu účastníka:** `disableInput(id, důvod)` / `enableInput(id, důvod)` (také na `Match`, platí i ve stavu
  `ended`) nastaví/odeberou zámek s důvodem z oddílu 6 na **všech** zbraních účastníka, i na těch, které vzniknou až při
  pozdějším spawnu po změně výbavy. Respawn, reset kola ani změna výbavy je nezruší; snímek je ukazuje jako `inputLocks`.
  Výsledky: `ok`, `unknown_id`, `invalid_reason`.
- **Poškození** je celé kladné číslo. Friendly fire je vypnutý: poškození od spoluhráče se zahodí (`blocked_friendly_fire`).
  Poškození od sebe sama a od prostředí (`attacker = null`) se aplikuje. Nula nebo záporná hodnota = `invalid_amount`.
  Zdraví 0 = smrt. Poškození mrtvého = `not_alive`.
- Změna výbavy (`setLoadout`) se projeví až při dalším spawnu. Tým má nejvýše `teams.size` členů (`team_full`).

## 6. Zbraň: munice, kadence, přebití (GUN-01)

### Model munice
- Zásobník (`magazine`), **komora evidovaná samostatně** (`chamber` 0/1) a rezerva (`reserve`). Puška 30+1, pistole 15+1.
- Výstřel vyžaduje náboj v komoře. Po výstřelu se další náboj přesune ze zásobníku do komory. Je-li zásobník po výstřelu
  prázdný, závěr zůstane vzadu (komora prázdná, událost `bolt_locked`).
- Zbraň s `hasChamber: false` (podporováno pro budoucí zbraně) střílí přímo ze zásobníku a nemá uvolnění závěru ani nabíjení.

### Kadence a spoušť
- Palebný interval = `60 / roundsPerMinute` s (puška 80 000 µs, pistole 133 333 µs) a počítá se **akumulátorem času**,
  ne délkou snímku: počet i časy výstřelů za interval jsou stejné pro 1/30, 1/60, 1/144 s i nepravidelné tiky.
- Plně automatický režim střílí, dokud je spoušť držená; poloautomatický jeden výstřel na stisk. Stisk během doběhu
  intervalu v poloautomatu vystřelí, jakmile interval uplyne (pokud je spoušť pořád držená); puštěním se stisk ruší.
- **Platnost stisku:** vystřelit smí jen stisk, který začal ve stavu `ready`. Stisk během přebíjení nebo nabíjení se ignoruje
  a po dokončení akce je nutné spoušť pustit a stisknout znovu (žádná střelba „sama“ po přebití). Totéž po změně režimu
  palby a po přerušení.
- Stisk s prázdnou komorou i zásobníkem = `dry_fire` (cvaknutí), munice se nemění.
- **Stisk = hrana puštěno → drženo mezi dvěma voláními `update`.** Poslední pozorovaný stav spouště (`triggerPrev`) se
  nemění při `disable`, `enable` ani `resetToLoadout`. Spoušť držená přes smrt, menu, respawn nebo reset výbavy proto
  nevystřelí, dokud se nepustí a znovu nestiskne; stisk, který začne po respawnu (po předchozím puštění), vystřelí hned.

### Vypnutí zbraně (GUN-03: po otevření menu nebo smrti nesmí pokračovat vstup pro palbu)
- Zbraň má sadu **nezávislých zámků**. Zbraň přijímá spoušť a přebití, jen když není nastavený žádný (`enabled`);
  snímek je ukazuje jako `disabledBy` v pevném pořadí `life`, `sprint`, `switch`, `menu`, `results`, `other`.
- `disable(důvod)` s důvodem `sprint`, `switch`, `menu`, `results` nebo `other` (JS `DISABLE_REASONS`, C++ `DisableReason`)
  přidá zámek: přeruší probíhající přebíjení/nabíjení (`sprint` → důvod přerušení `sprint`, `switch` → `switch`, ostatní
  → `other`), zruší platný stisk. Opakované vypnutí stejným důvodem nic nemění. Dokud trvá jakýkoli zámek, spoušť se
  ignoruje (stav spouště se ale dál sleduje), `reload()` vrací `rejected_disabled`; čas (hodiny zbraně, doběh palebného
  intervalu) plyne dál. Režim palby a doplnění munice fungují.
- `enable(důvod)` odebere **jen** zámek s tímto důvodem; ostatní zámky (jiný důvod, zámek života) trvají. Odebrání
  nenastaveného zámku nic nedělá. Jiný důvod (`death`, `life`, chybějící, neznámý) = `invalid_reason`. Když zmizí poslední
  zámek, vystřelit smí až nový stisk.
- Zámek života (`life`) nastavuje a odebírá jen `RespawnSystem` (oddíl 5). Engine používá vlastní důvody: menu → `menu`,
  výsledková obrazovka → `results`, sprint → `sprint`, uložená zbraň → `switch`. Pro menu a výsledky je vhodnější
  `disableInput`/`enableInput` na účastníkovi (platí i pro zbraně vzniklé později). Menu otevřené během smrti a zavřené
  před respawnem tak zbraň nezapne, a respawn s otevřeným menu ji nezapne také.
- **Kontrakt pro engine:** `update(dt, spoušť)` volat každý snímek se skutečným stavem spouště i na vypnutou zbraň. Pokud by
  engine vypnutou zbraň neaktualizoval, stisk, který začal během vypnutí a trvá i po zapnutí, by se jevil jako nový.

### Přebití
Rozhodnutí při požadavku `reload()`:

| Stav | Výsledek |
| --- | --- |
| zbraň vypnutá (mrtvý účastník, menu) | `rejected_disabled` |
| probíhá přebíjení nebo nabíjení | `rejected_busy` |
| komora prázdná, zásobník neprázdný a (zásobník plný nebo rezerva 0) | `started_chamber` — jen nabití, zásobník se nemění |
| rezerva 0 | `rejected_no_reserve` |
| zásobník plný a náboj v komoře | `rejected_full` |
| náboj v komoře | `started_tactical` |
| komora prázdná | `started_empty` |

- **Taktické přebití** (náboj v komoře zůstává): commit *vložení zásobníku* v čase `insertCommit`, konec v `duration`.
- **Přebití z prázdna:** commit vložení v `insertCommit`, commit *uvolnění závěru* v `boltRelease` (náboj ze zásobníku do komory),
  konec v `duration`.
- **Politika „retained magazine“:** vyjmutý zásobník se neztrácí — jeho náboje se při commitu vložení vrátí do rezervy a
  nový zásobník se naplní z rezervy: `pool = reserve + magazine; magazine = min(kapacita, pool); reserve = pool − magazine`.
  Vyjmutí a vložení jsou z hlediska munice jediná atomická transakce v okamžiku vložení. Hráč tak nikdy neztratí náboje;
  výsledek odpovídá doplnění `min(kapacita, zásobník + rezerva)`.
- Každý přesun munice proběhne **právě jednou** v explicitním commitu na časové ose akce (vložení, uvolnění závěru, nabití),
  nikdy z animační události. Animace a zvuk reagují na události jádra (`mag_insert`, `bolt_release`, …), ne naopak.
  Přebití je logicky hotové (`reload_complete`) v okamžiku `duration`, kdy je zbraň připravená ke střelbě.
- **Přerušení** (`sprint`, `switch`, `death`, `other`):
  - před commitem vložení → munice se nemění (starý zásobník zůstává);
  - po vložení, před uvolněním závěru → nový zásobník zůstává, komora prázdná; **další stisk spouště provede krátkou
    explicitní akci nabití** (`chamber_start` → commit v `chamber.commit` → `chamber_complete`), teprve další stisk střílí;
  - po uvolnění závěru → zbraň je nabitá.
  - Přerušení nabíjení před jeho commitem nic nemění; potřeba nabití trvá.
- **Doplnění munice** (`resupply`) přidává do rezervy nejvýše do `maxReserve`; přidané množství se eviduje.
- **Respawn** resetuje zbraň na výchozí výbavu včetně stavu přebíjení a čítačů (`resetToLoadout`); poslední pozorovaný stav
  spouště a zámky se resetem nemění. Probíhající akci `resetToLoadout` nejdřív přeruší s důvodem `other` (událost
  `reload_interrupted` / `chamber_interrupted`) a **nesmaže** dosud neodebrané události. Animace a zvuk tak vždy dostanou
  konec akce, i při `Match.reset()` a při okamžitém respawnu (GUN-01, SND-01). Hodiny zbraně (`atUs`) po resetu začínají
  od 0; události před resetem nesou čas na starých hodinách. Engine má pohled zbraně (ruka na zbrani, závěr, zásobník)
  resetovat i na událost respawnu `spawned` a po `Match.reset()`.

### Invariant (kontrolovaný v testech po každém tiku)
`zásobník + komora + rezerva == počáteční_stav − vystřeleno + doplněno`, žádná hodnota není záporná ani nad kapacitou
(`zásobník ≤ kapacita`, `komora ≤ 1`, `rezerva ≤ maxReserve`). Explicitní ztráta munice se neimplementuje.

### Události zbraně
`shot`, `bolt_locked`, `dry_fire`, `reload_start` (tactical/empty), `mag_insert`, `bolt_release`, `reload_complete`,
`reload_interrupted` (důvod), `chamber_start`, `chamber_commit`, `chamber_complete`, `chamber_interrupted` (důvod).
Každá nese přesný čas `atUs` na hodinách zbraně.

## 7. Fasáda zápasu (`Match`)

`Match.update(dt, svět)` dělí tik v okamžicích pokusů o spawn:

1. na začátku tiku proběhnou spawny, jejichž odpočet už je 0 (nový účastník, po resetu kola);
2. pro každý úsek do nejbližšího pokusu o spawn (nebo do konce tiku) se sestaví účastníci oblasti se stavem života
   na **začátku** úseku (`inZone` a `active` dodá engine, platí po celý tik) a proběhne tik kola;
3. na konci úseku proběhnou pokusy o spawn, které na něj připadají, a pokračuje se dalším úsekem.

Respawnutý účastník se tak v oblasti počítá **přesně od okamžiku spawnu** a body nezávisí na délce tiku. Skončí-li kolo
uprostřed úseku (dosažením cíle i vypršením časového limitu), odpočty respawnu i rezervace bodů doběhnou jen do okamžiku
konce (vektory `GAME-01/match-*-mid-segment-freezes-pending-respawn`). Rezervace bodů (oddíl 5) platí přes úseky i tiky.
Ve stavu `ended` je `update` bez účinku (skóre, čas i respawny stojí).
Snímek stavu po tiku ukazuje oblast tak, jak byla vyhodnocena v posledním úseku (respawn přesně na konci tiku se v počtech
projeví až v dalším tiku).

## 8. Determinismus a shoda JS / C++

- Celočíselný čas, generátor mulberry32 (32bit stav; `pickIndex(n) = floor(u32 · n / 2^32)`; míchání Fisher–Yates od konce),
  vzdálenosti v `double` se stejným pořadím operací; C++ se překládá s `-ffp-contract=off` (bez FMA).
- Jádra nepoužívají `Math.random`, hodiny ani DOM (hlídá `core_purity.test.mjs`).
- **Ruční vektory** (`weapon`, `zone`, `round`, `respawn`, `match`, `rules`, `rng`): očekávané hodnoty jsou odvozené
  ručně z těchto pravidel, ne z testovaného jádra. Hodnoty závislé na semeni (výběr oblasti, body spawnu, výstupy generátoru)
  nezávisle přepočítává referenční implementace v Pythonu **`Shared/testvectors/tools/seed_reference.py`**, která nepoužívá
  JS ani C++ jádro: kontroluje celý `rng.json`, `zoneIndex`/`zoneId` ve všech vektorech kola a zápasu (ruční i fuzz)
  a výsledky, události a pole životního cyklu respawnu včetně bodů spawnu, rezervací (`reservedUs`) a zámků vstupu
  (`inputLocks`) v `respawn.json` i `fuzz_respawn.json`.
  Spouští ji ctest (test `seed_reference`, je-li nalezen Python 3) nebo přímo `python3 Shared/testvectors/tools/seed_reference.py`.
- **Diferenciální fuzz** (`fuzz_*.json`): generátor `Web/tests/unit/support/fuzz_generator.mjs` vytvoří náhodné, ale platné
  posloupnosti akcí (munice, oblast, kolo, respawn, zápas), JS jádro dopočítá výsledek, události a stav po každém kroku.
  C++ test přehraje stejné soubory: výsledek a události se porovnávají přesně, stav přes FNV-1a 64 kanonického JSON
  celého stavu (seřazené klíče, bez mezer) a každý 10. a poslední krok i celý stav pole po poli.
  JS test navíc hlídá, že uložené soubory odpovídají aktuálnímu generátoru.
- **Kontrola tvaru vektorů:** oba spouštěče odmítnou chybou případu neznámý klíč případu, `setup`, kroku, `do` nebo těla,
  `expect` uvnitř `loop`/`do` (tam se nekontroluje), nelogickou hodnotu `trigger`/`alive`/`active`/`inZone` a režim tiku
  s jiným počtem klíčů než jedním. Soubor `Shared/testvectors/malformed/cases.json` (dvojice chybný případ + tentýž bez
  chyby) to ověřuje v JS (`core_runner.test.mjs`) i v C++ (`ctest` `runner.malformed`).

## 9. Rozhodnutí o nejasnostech zadání

| # | Nejasnost | Rozhodnutí |
| --- | --- | --- |
| R1 | Co přesně je stav `dead` a co `respawning` | `dead` = odpočet `delay`; `respawning` = odpočet doběhl, čeká se na bezpečný bod (pokus hned, pak po `retryInterval`). |
| R2 | Postup bodu při změně složení stejného týmu | Nenuluje se (kontrolor se nezměnil). Nuluje se jen při změně kontrolora nebo při sporu/prázdnu. |
| R3 | Bod přesně v čase limitu | Započítá se; dosáhne-li jím tým cíle, konec je `score_target`. |
| R4 | Kdy přesně končí kolo při dosažení cíle uprostřed tiku | V okamžiku posledního bodu (zbytek tiku se zahodí); `elapsed` je přesný. |
| R5 | Odpočet před kolem | Přidán `preRoundDuration` 5 s (datově), během něj se neboduje; `start()` ho přeskočí. |
| R6 | Opakování stejné oblasti v dalším kole | Povoleno (čistě náhodný výběr ze semene). |
| R7 | Výstřel přesně na hranici tiku | Patří dalšímu tiku (polootevřený interval); milníky akcí na hranici proběhnou v aktuálním tiku. |
| R8 | Střelba po dokončení přebití s drženou spouští | Ne — je nutný nový stisk. Stejně po nabití, přerušení a změně režimu. |
| R9 | Stisk spouště během přebíjení | Ignoruje se (přebití nepřeruší); přerušit lze jen sprintem/výměnou/smrtí. |
| R10 | Stisk po přerušení po vložení zásobníku | Stisk spustí jen akci nabití; výstřel vyžaduje další stisk. |
| R11 | `reload()` se zásobníkem plným a prázdnou komorou (nebo bez rezervy) | Provede jen akci nabití (`started_chamber`). |
| R12 | Co se stane s nábojem z vyjmutého zásobníku | Politika „retained magazine“: vrací se do rezervy, přesun je atomický v okamžiku vložení. |
| R13 | Počítá se v oblasti účastník respawnutý v tomtéž tiku | Ano, ale až od přesného okamžiku spawnu (`Match` tik v okamžicích spawnu dělí), takže body nezávisí na délce tiku. |
| R14 | Poškození od sebe sama při vypnutém friendly fire | Aplikuje se (není to friendly fire). Poškození od prostředí také. |
| R15 | Dva spoluhráči spawnující ve stejném tiku | Bod použitý pro spawn je rezervovaný na `retryInterval` času jádra (ne na jeden tik), takže výsledek nezávisí na délce tiku; po rezervaci rozhoduje predikát, kterému engine mezi tiky předává polohy těl. |
| R16 | Vzdálenost „N m od živých nepřátel“ | 3D eukleidovská, ostrá nerovnost; mrtvá těla se ignorují. |
| R17 | Zabití/poškození po konci kola | Odmítnuto (`round_ended`); respawny ve stavu `ended` stojí. |
| R18 | Po konci kola časovým limitem zbylý postup | Vynuluje se (stav `ended`). |
| R19 | Výběr spawnu je náhodný nebo podle priority | Náhodné pořadí ze semene (deterministické); engine může priority vyjádřit predikátem. |
| R20 | Palba a přebití mrtvého; spoušť držená přes smrt, menu nebo respawn (GUN-03) | Zbraně účastníka, který není `alive`, mají zámek života: spoušť se ignoruje, `reload` → `rejected_disabled`. Vystřelit smí jen nový stisk (hrana v `update`); spoušť držená přes smrt/menu/respawn/reset výbavy nevystřelí, dokud se nepustí. |
| R21 | Jak dlouho platí reference enginu na zbraň | Po celou dobu života `RespawnSystem`/`Match` (respawn, reset kola, přidání účastníků i změna výbavy); zbraň mimo výbavu má zámek života. |
| R22 | Menu nebo výsledky během smrti a respawnu | Každý důvod vypnutí je samostatný zámek; `enable(důvod)` odebere jen svůj. Zavření menu mrtvého nezapne, respawn nezapne zbraň s otevřeným menu. Zámek života drží jen `RespawnSystem`. |
| R23 | Skóre nad rozsah 32bitového čísla | Přesné celé číslo do 2^53 − 1, pak saturace (JS i C++ stejně). |
| R24 | Neoverená pravidla v C++ (vlastní parser enginu) | Konstruktory je zkontrolují; při chybě jsou operace bez účinku (`invalid_config`), nic nespadne ani nezamrzne. |

## 10. Pokrytí požadavků testy

| Požadavek | Případy (id ve vektorech) |
| --- | --- |
| GAME-01 prázdná oblast / jeden přítomný / převaha | `GAME-01/empty-zone-scores-nothing`, `GAME-01/one-present-scores-every-2s`, `GAME-01/majority-controls`, `GAME-01/unique-top-team-wins-over-tied-lower-teams` |
| GAME-01 shoda dvou / tří týmů | `GAME-01/tie-of-two-teams-stops-scoring`, `GAME-01/tie-drops-previous-owner-progress`, `GAME-01/tie-of-three-teams` |
| GAME-01 smrt uvnitř, mrtví/neaktivní | `GAME-01/death-inside-zone`, `GAME-01/dead-respawning-and-inactive-never-count`, `GAME-01/match-inactive-participants-not-counted`, `GAME-02/full-match-cycle-3x6` |
| GAME-01 rychlý vstup/výstup, změna kontrolora | `GAME-01/fast-enter-exit-never-scores`, `GAME-01/controller-change-resets-progress` |
| GAME-01 konec cílem / časem / remíza | `GAME-01/score-target-*`, `GAME-01/time-limit-*`, `GAME-01/target-reached-exactly-at-time-limit-counts-as-target` |
| GAME-01 vynulování bez zbytků časovačů | `GAME-01/reset-*`, `GAME-01/match-reset-leaves-no-timers`, `GAME-02/reset-round-clears-pending-respawns` |
| GAME-02 respawn (≥ 3 smrti, zdraví, výbava) | `GAME-02/three-deaths-with-delay`, `GAME-02/respawn-restores-full-loadout`, `GAME-02/full-match-cycle-3x6` |
| Bezpečný spawn | `RESPAWN/no-safe-point-waits-and-retries`, `RESPAWN/living-enemies-block-nearby-points`, `RESPAWN/enemy-distance-boundary-is-strict`, `RESPAWN/body-clearance-applies-to-teammates`, `RESPAWN/point-claimed-in-same-update-is-not-reused`, `RESPAWN/spawn-point-reservation-spans-updates` |
| GUN-01 střelba z plného, poslední náboj, prázdný | `GUN-01/fire-from-full`, `GUN-01/last-round-locks-bolt`, `GUN-01/empty-whole-magazine-in-auto`, `GUN-01/empty-dry-fire-and-no-reserve` |
| GUN-01 přebití částečné, z prázdna, nedostatek rezervy, rezerva 0 | `GUN-01/partial-tactical-reload`, `GUN-01/empty-reload-chambers-at-bolt-release`, `GUN-01/*-insufficient-reserve`, `GUN-01/reserve-zero-no-reload`, `GUN-01/full-magazine-with-chamber-no-reload` |
| GUN-01 přerušení před/po vložení, před uvolněním závěru + nabití | `GUN-01/interrupt-before-insert-changes-nothing`, `GUN-01/interrupt-empty-reload-before-insert`, `GUN-01/interrupt-after-insert-tactical-keeps-new-magazine`, `GUN-01/interrupt-before-bolt-release-then-chamber-action`, `GUN-01/chamber-action-interrupted-before-commit`, `GUN-01/interrupt-after-bolt-release` |
| GUN-01 jednorázové commity, respawn | `GUN-01/commits-happen-once-in-one-large-tick`, `GUN-01/respawn-resets-weapon-mid-reload` |
| GUN-01 nezávislost na FPS | `GUN-01/frame-rate-independence` (1/30, 1/60, 1/144, 1/7, 1 ms, 80 ms, jeden obří tik, 3× nepravidelné), plus 200 náhodných rozdělení v `core_weapon.test.mjs` a `ivcore_unit` |
| GUN-03 smrt/menu: žádná palba ani přebití, spoušť držená přes smrt/respawn/reset | `GUN-03/disable-reasons-are-independent-locks`, `GUN-03/match-menu-closed-while-dead-weapon-stays-inert`, `GUN-03/match-respawn-keeps-menu-lock`, `RESPAWN/new-weapon-inherits-participant-input-lock`, `GUN-03/disabled-weapon-ignores-trigger-and-reload`, `GUN-03/disable-before-insert-interrupts-reload-and-blocks-new-reload`, `GUN-03/disable-after-insert-keeps-magazine-then-chamber-action`, `GUN-03/trigger-held-through-reset-to-loadout-does-not-fire`, `GUN-03/dead-participant-weapon-is-inert-and-held-trigger-needs-release`, `GUN-03/match-dead-participant-weapon-must-not-fire`, `GUN-03/match-trigger-held-through-respawn-must-not-fire` |
| Respawn uprostřed tiku nezávislý na délce tiku | `GAME-01/match-respawn-inside-tick-counts-from-spawn-instant`, `RESPAWN/retries-inside-one-long-tick-are-tick-independent`, `RESPAWN/single-free-point-two-spawners-tick-independent`, `GAME-01/match-single-free-point-scores-tick-independent` (každý v 5–6 režimech tiku), `RESPAWN/spawn-point-reservation-spans-updates` |
| Konec kola uprostřed úseku zastaví odpočty respawnu | `GAME-01/match-time-limit-mid-segment-freezes-pending-respawn`, `GAME-01/match-score-target-mid-segment-freezes-pending-respawn` (5 režimů tiku) |
| Události přerušení při resetu a okamžitém respawnu | `GUN-01/respawn-resets-weapon-mid-reload`, `GUN-01/match-reset-reports-interrupted-reload`, `GUN-01/reload-interrupted-event-survives-reset-and-instant-respawn` |
| Skóre nad 2^31, saturace | `GAME-01/zone-score-exact-beyond-32-bit-and-saturates`, `ivcore_unit`, `core_api.test.mjs` |
| Neoverená pravidla v C++, dt nad 2^53 − 1 | `ivcore_unit` (`Rules{}`, `pointInterval` 0, `pointsPerAward` 0, `retryInterval` 0 / záporný, neplatná zbraň) |
| Spouštěč neignoruje chybné vektory | `Shared/testvectors/malformed/cases.json` (`core_runner.test.mjs`, `ctest runner.malformed`) |
| Platnost referencí/ukazatelů na zbraně | `core_api.test.mjs` (respawn, `Match.reset`, změna výbavy), `ivcore_unit` (totéž + přidání účastníků; s `-DIV_SANITIZE=ON` odhalí use-after-free) |
| Záporné `dt` | `core_api.test.mjs` (JS `RangeError`), `ivcore_unit` (C++ bez účinku, `InvalidDt`) |
