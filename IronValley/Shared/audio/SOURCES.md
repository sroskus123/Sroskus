# IRON VALLEY — zvuky: zdroje, licence, úpravy

Generováno skriptem `Tools/audio/write_sources.py` z `Tools/audio/sources.json` a `Web/src/data/audio_bank.json`.
Runtime soubory: `Web/public/assets/audio/*.mp3` (44,1 kHz, VBR MP3). Build: `python3 Tools/audio/fetch_sources.py`
(stáhne zdroje a ověří SHA-256) → `python3 Tools/audio/build_audio.py` (střih, filtry, normalizace, syntéza, MP3,
kontrolní spektrogramy v `Tools/audio/_out/`) → `python3 Tools/audio/write_sources.py`.

**Pravidla:** jen CC0 / volné dílo / CC BY (s uvedením autora — tady i v textu „Ovládání → Zvuky — autoři a licence“
ve hře). Nic NC/ND, žádné „royalty-free s omezením“, žádné nejasné licence. Co nešlo legálně získat, je
**procedurální syntéza — prozatímní** (ne finální asset, SND-01: „chybějící kvalitní zvukový asset pojmenuj“).

Nikdo zvuky neposlouchal (prostředí nemá výstup zvuku). Ověřeno objektivně: spektrogramy a průběhy (prohlédnuté
PNG), délky, špička (true peak, 4× převzorkování) a RMS, dekódování v Chromiu (e2e), úroveň výsledného mixu přes
skutečný řetězec master sběrnice (`Web/tools/audio_mixcheck.mjs`).

## Plán hlasitosti (úroveň souboru, před mixem)

| Skupina | Cíl |
| --- | --- |
| vlastní výstřel puška (blízko) | true peak −3 dBFS |
| vlastní výstřel pistole (blízko) | true peak −4 dBFS |
| vzdálené varianty výstřelů | true peak −6 dBFS (útlum vzdáleností za běhu) |
| dozvuk (tail) venku | true peak −9 dBFS |
| zásahy / průlet střely | true peak −8 / −6 dBFS |
| mechanika zbraní | true peak −10 dBFS (cvaknutí naprázdno −14) |
| oblečení / výstroj | true peak −12 až −16 dBFS |
| kroky | aktivní RMS −24 dBFS (okna 10 ms do 30 dB pod maximem; když by špička přesáhla −1 dBFS, soubor se ztiší) |
| ambience (vítr, ptáci) | RMS −36 dBFS |

Za běhu: kategorie → master (hlasitost, výchozí 70 %) → kompresor → limiter (automatický make-up gain je
vyrušen) → měkký ořez. Změřeno v Chromiu (OfflineAudioContext, hlasitost 70 %): vlastní výstřel puškou špička
≈ −10 dBFS (max. RMS 10 ms ≈ −16), dávka 12 ran ≈ −10 dBFS, pistole ≈ −11 dBFS, přebíjení ≈ −15 dBFS, kroky max. RMS
10 ms ≈ −29 (běh) / −33 dBFS (chůze), vítr RMS ≈ −41 dBFS, přestřelka (12 vlastních + 48 cizích ran, zásahy, průlety)
špička ≈ −8 dBFS, 0 vzorků na plné úrovni.

## Balíčky zdrojů a doklad licence

| Balíček | Autor | Licence | Stránka | Doklad licence / ověření bajtů |
| --- | --- | --- | --- | --- |
| `ffsl` — The Free Firearm Sound Library — Prepared SFX Library | Ben Jaszczak, Brian Nelson, Kevin Heras, Matthew Nanney (OGA upload: bart) | CC0 1.0 (volné dílo) | https://opengameart.org/content/the-free-firearm-sound-library | OGA page text: "Our team holds CC0 NO RIGHTS RESERVED for this library. It may be used without royalty or credit" (snapshot: https://raw.githubusercontent.com/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/guns.html). Mirror bytes verified: C_28P.wav from the mirror = LFS oid e0934c1d… of the file extracted from the original OGA archive "Prepared SFX Library.7z" (sha256 cc1ab5a9…) in RolandSallaz/CounterMine-2; Prepared Master Sheet.csv sha256 98e3ce7f… identical to the copy recorded by AetherRadar/operation-steel-tide. |
| `lfa` — equipment clicks III (bolt-action rifle, stapler, tape measure) | LFA | CC0 1.0 (volné dílo) | https://opengameart.org/content/equipment-clicks-iii | OGA page snapshot https://raw.githubusercontent.com/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/clicks.html (licence field CC0); original download URL https://opengameart.org/sites/default/files/equipment_clicks3.wav, sha256 recorded in that repo's downloads.json = this file. |
| `springy` — Gun reload sounds (recorded with airsoft guns) | SpringySpringo | CC0 1.0 (volné dílo) | https://opengameart.org/content/gun-reload-sounds | OGA page snapshot https://raw.githubusercontent.com/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/reload.html (licence CC0). assaultriflereload1_0.wav sha256 = downloads.json of that repo (downloaded from OGA); gunreload1.wav identical in 3 independent repos (YourKindAlly/CaptureFlag, fighter-435/Break-the-Battle-Formation, Lucasdelpiero/TopDownShooter). |
| `kenney_impact` — Impact Sounds 1.0 | Kenney (www.kenney.nl) | CC0 1.0 (volné dílo) | https://kenney.nl/assets/impact-sounds | Pack License.txt ("License: (Creative Commons Zero, CC0)") shipped with the files in hellochar/Twilight-Dungeons Assets/Audio/kenney_impactsounds/; all 130 downloaded files byte-identical to that repo's Git-LFS oids. |
| `kenney_rpg` — RPG Audio 1.0 | Kenney (www.kenney.nl) | CC0 1.0 (volné dílo) | https://kenney.nl/assets/rpg-audio | Pack License.txt (CC0) in series-ai/jam-ready-assets kenney-rpg-audio/audio/License.txt, files from the same folder. |
| `fantozzi` — Fantozzi's Footsteps (Grass/Sand & Stone) | Fantozzi (recording), qubodup (editing/upload) | CC0 1.0 (volné dílo) | https://opengameart.org/content/fantozzis-footsteps-grasssand-stone | Credits in furudbat/vimjam5 godot/assets/sounds/CREDITS (CC0) and provenance JSON with page snapshot in ShmuelSokol/3rdbhmk; files byte-identical between goatchurchprime/gamejamenchanted and furudbat/vimjam5 (LFS oids). |
| `cdogs` — Footsteps on different surfaces (mastered for C-Dogs SDL) | congusbongus (Cong Xu), derived from freesound: Ali_6868 (gravel, CC0), Eelke (metal, CC BY) | per surface: see licence.txt | https://opengameart.org/content/footsteps-on-different-surfaces | Per-folder license.txt in cxong/cdogs-sdl sounds/footsteps/<surface>/license.txt; OGA page snapshot https://raw.githubusercontent.com/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/steps.html (CC-BY 3.0); files identical to the OGA archive footsteps_0.zip (sha256 542564e7…). |
| `librosa` — Bird Whistling, Robin, Single, 13.wav | InspectorJ (freesound.org) | CC BY 4.0 (uvést autora) | https://freesound.org/people/InspectorJ/sounds/456440/ | librosa/data audio/456440__inspectorj__bird-whistling-robin-single-13.toml (license = "CC-BY-4.0"); sha256 matches librosa/data index/registry.txt. |

C-Dogs kroky (`cdogs`) mají licenci po površích (`license.txt` ve složce): štěrk = Ali_6868, CC0 1.0; kov = Eelke, CC BY 4.0 (OGA text balíčku uvádí CC BY 3.0 — obojí jen vyžaduje uvést autora); úprava congusbongus (OpenGameArt „Footsteps on different surfaces“, CC BY 3.0).

## Staženo (připnuto SHA-256)

| Soubor v `_src/` | URL | SHA-256 |
| --- | --- | --- |
| `ffsl/D_24P.wav` | https://raw.githubusercontent.com/petroulacl/fps-asset-kit/main/sfx/firearm_sfx/Prepared%20SFX%20Library/AR-15/D_24P.wav | `4c6a54ca0583150bbb32b7f658bc64da9ad9ba42fd3aca769c6120b44af8d3f0` |
| `ffsl/D_32P.wav` | https://raw.githubusercontent.com/petroulacl/fps-asset-kit/main/sfx/firearm_sfx/Prepared%20SFX%20Library/AR-15/D_32P.wav | `acee9d2106b68fe5956225a19d7aedf943d97793817f9bda9d486a2b74b0a812` |
| `ffsl/X_31P.wav` | https://raw.githubusercontent.com/petroulacl/fps-asset-kit/main/sfx/firearm_sfx/Prepared%20SFX%20Library/Walther%20PPQ/X_31P.wav | `b6439228ca46b37c00463265028094559ae5c9896c796b5d40ea4f33247f149c` |
| `ffsl/X_39P.wav` | https://raw.githubusercontent.com/petroulacl/fps-asset-kit/main/sfx/firearm_sfx/Prepared%20SFX%20Library/Walther%20PPQ/X_39P.wav | `d679a3cd87eae2898d984159f83544392932e6b77526045b672e3aaa9c2dda9f` |
| `lfa/equipment_clicks3.wav` | https://media.githubusercontent.com/media/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/equipment_clicks3.wav | `1cd2612f226886a7c0badbe26e9732e097a448e97cbea72a3e3cd2c8aa91ace8` |
| `springy/assaultriflereload1_0.wav` | https://media.githubusercontent.com/media/RolandSallaz/CounterMine-2/main/Documentation/AudioSources/assaultriflereload1_0.wav | `efb2d724d634eabe6ba8d3065686abca848bb7497d4d43a5e4aed5e5ea23016f` |
| `springy/gunreload1.wav` | https://raw.githubusercontent.com/YourKindAlly/CaptureFlag/main/assets/audio/sfx/gunreload1.wav | `685cac6a184e3cc3ec09a25b6ddb1d6feffd86d469778f339aa423d384035c50` |
| `librosa/robin.hq.ogg` | https://raw.githubusercontent.com/librosa/data/main/audio/456440__inspectorj__bird-whistling-robin-single-13.hq.ogg | `a3b3ecf749befde43bdf35f839fdcb8d399a4deb5666de6f399c35ce12936baa` |
| `fantozzi/Fantozzi-SandL1.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandL1.ogg | `fe6ec00cbe8790be0f37540cb8db8d245ca062337b121003685b6a96700cd0ae` |
| `fantozzi/Fantozzi-SandL2.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandL2.ogg | `68ba66063efa32b3a83979194582b1420f808cd217ccb5839c382d0e08522e18` |
| `fantozzi/Fantozzi-SandL3.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandL3.ogg | `0a526053424687c18735bca107b7234e48aceeb6bf12eec1f182d89aaf792b71` |
| `fantozzi/Fantozzi-SandR1.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandR1.ogg | `439ffe4d6fdf38194caf87e103897354756d69607bd4e48cef923e1ade68ee70` |
| `fantozzi/Fantozzi-SandR2.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandR2.ogg | `5eec48117da8fa433963ba06a93f67705f0bbd86ac3f473ab7b3bd120bf55fce` |
| `fantozzi/Fantozzi-SandR3.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-SandR3.ogg | `7498c4e50282acc4e7e0442a9f2e551fae685898f8261152dbc627f04901ddbe` |
| `fantozzi/Fantozzi-StoneL1.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneL1.ogg | `2d85768f04a85b6068f3548b33d6e0b0424c5e62b0941042d593affd3a9555d4` |
| `fantozzi/Fantozzi-StoneL2.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneL2.ogg | `1cdd36f02590d2b968b1dd311334e71db8514d7c276e62ad474d01c26b37d4de` |
| `fantozzi/Fantozzi-StoneL3.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneL3.ogg | `6e008bba3c24c6adc20151126768eba8c9259ec9f40b7c0b8399d60a9ca67812` |
| `fantozzi/Fantozzi-StoneR1.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneR1.ogg | `d6949efd0255d50efe4853cc077b18e3ee96b155707ccf4199fd530aaac82d58` |
| `fantozzi/Fantozzi-StoneR2.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneR2.ogg | `075c27afbf29b7771cb01a7bf51530b835e82c56698ca5551318fa0c6b7adb9f` |
| `fantozzi/Fantozzi-StoneR3.ogg` | https://raw.githubusercontent.com/goatchurchprime/gamejamenchanted/master/enchantedtree/sounds/Fantozzi-footsteps/ogg/Fantozzi-StoneR3.ogg | `73bbdfc3d9e891bc1afbab7050de3bd59adf13cf5145ff3fb2f1fa7b251d6d82` |
| `cdogs/gravel/0.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/0.ogg | `90d33dd0aff925581c97d8577a23d435e14089a789e7361792fd0ca69b888b54` |
| `cdogs/gravel/1.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/1.ogg | `9a7a083c54c10e5bedafc7f1473967fc074418e798b97c0ad378dcf49b91b35c` |
| `cdogs/gravel/2.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/2.ogg | `cdf6230d7e83d5b4bea374bfde49ea0e596c26755dbc35a1e07f520ff856edee` |
| `cdogs/gravel/3.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/3.ogg | `e535f14af2de8868809be1455f6d6fc10642f642e5f57d46ad4cecc726244bdf` |
| `cdogs/gravel/4.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/4.ogg | `0cd2f6771e69792c472c60d48146c8951566915a3da7ffd041325a4ea60c9352` |
| `cdogs/gravel/5.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/5.ogg | `b6f2f32e114c92e8f2ee6fdcf22abb7452ee339c9c4fa37e158e1e601cde9e32` |
| `cdogs/gravel/6.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/6.ogg | `0621550377dc4566facfbdb4a50a13f09c9d67e56848ec53a7899f948c0a4652` |
| `cdogs/gravel/7.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/7.ogg | `6c4316d2fd702bbb337789fac46d68cbad60ce5cbdc4261d5e4cc29041c4c82e` |
| `cdogs/gravel/8.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/8.ogg | `8fe7d1d6cf9c77ef4d135c2315db0fad841656c352c5f5b71b4dbf0e1cae9828` |
| `cdogs/gravel/9.ogg` — Ali_6868, freesound pack 21608, CC0-1.0, https://freesound.org/people/Ali_6868/packs/21608/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/gravel/9.ogg | `3828235f14cb0b9044160febe334b41d55305e016a7bfa809e2e768dc1eb4650` |
| `cdogs/metal/0.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/0.ogg | `c4e3dbf5d4000b98aca5a06c210cc8b38644cc16b3e291453aee1e2afac4cd3e` |
| `cdogs/metal/1.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/1.ogg | `d9a8005ce36786ce98d565961b6c506e83a9b99f5af8ef47d37692197ae55862` |
| `cdogs/metal/2.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/2.ogg | `8d9d7378a393ddbd4e5b44ea4ba49df775108ffdf9c943dda88aa5fe5de0572c` |
| `cdogs/metal/3.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/3.ogg | `3d619b68ec3e8e1d92429a9d21b370f6d36a8d4a6576d4d240057c335a181ffe` |
| `cdogs/metal/4.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/4.ogg | `8cf3a86a63de1b7c2a6412d7342a131e3882de039c8116dc8f966d106bcc0696` |
| `cdogs/metal/5.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/5.ogg | `81f31cbe3ede086c6f0588602a34826b5c6eacc1c3b956092cf55f2b76db81f6` |
| `cdogs/metal/6.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/6.ogg | `97b779681d7fcbcad936da098f53c19416475bd4ab27813bed5eac7dcc919382` |
| `cdogs/metal/7.ogg` — Eelke, "fboots on aluminum ladder 01", CC-BY-4.0 (C-Dogs licence.txt; OGA pack text says CC-BY-3.0), https://freesound.org/people/Eelke/sounds/462598/ | https://raw.githubusercontent.com/cxong/cdogs-sdl/master/sounds/footsteps/metal/7.ogg | `b330ac4f2b147808920b12153c5a81433bbf233f48c942fc5dddedd2586631aa` |
| `kenney_rpg/cloth1.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/cloth1.ogg | `3598f30f9afa294e4834fab7a3b1b76fbd0588607fdcd848fc87c2c9a0011d3f` |
| `kenney_rpg/cloth2.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/cloth2.ogg | `0ddc67e4cdf09740232c4d2f4a0e7b49b0d7d76268da6fc10431107f0fc742d1` |
| `kenney_rpg/cloth3.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/cloth3.ogg | `05c08d8093545dd18cd057da71cb36377469bfa2b9487098000c99844e599631` |
| `kenney_rpg/cloth4.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/cloth4.ogg | `319705aab5795c4c514cb7c62e0611926011ec9566f50525350e32863e47c29b` |
| `kenney_rpg/clothBelt.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/clothBelt.ogg | `ae53b7c3a69c4258e4aeac46884d4c56d807d74eac1dc6b38ff99bdf58df4217` |
| `kenney_rpg/clothBelt2.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/clothBelt2.ogg | `0478e09c1e86af49d56a4e7b399c38025cdf66d78517219327be50c27c8512c7` |
| `kenney_rpg/beltHandle1.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/beltHandle1.ogg | `d9dde0c56bba2986f63e84eddd83111f33f15e819f5cdd8f5d46bb451ce8a8de` |
| `kenney_rpg/beltHandle2.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/beltHandle2.ogg | `c67053a55b1224478231dea925c9bace63f539a59c0a366dedd6326c9d932255` |
| `kenney_rpg/metalClick.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/metalClick.ogg | `a510eee39fd16aadb47944198a32f333c03b9f839b2da119eb4c449796d27bb6` |
| `kenney_rpg/metalLatch.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/metalLatch.ogg | `ea762526168b6ebeeefeb5a620be2b95a8da53e71ba8d7a2b736560ee00011d0` |
| `kenney_rpg/handleSmallLeather.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/handleSmallLeather.ogg | `37fde28abdd317a47e0c02d5ce9a33201a93833b97fa43b40d7b38dffc3bc949` |
| `kenney_rpg/handleSmallLeather2.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/handleSmallLeather2.ogg | `19d30666fb3b53cb68c120c87e102ed4f784cd278ee1c746a8d43d3493253f85` |
| `kenney_impact/footstep_grass_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_grass_000.ogg | `9d49497777405d78d7cf7f2888e28277f3a23192300cfd1d79d54876b20f479f` |
| `kenney_impact/footstep_grass_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_grass_001.ogg | `fb28781bd22b2eefdc14077f1adf5c94d7fe9c3a130194633b55f3e0d39d9f04` |
| `kenney_impact/footstep_grass_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_grass_002.ogg | `73a520139f5be716a403bfe9c80e0e94d1e61d8e9de04a354b336392164b53dc` |
| `kenney_impact/footstep_grass_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_grass_003.ogg | `0546e1d8ab2def714425701a18bd34c5ee2794b12e858e5b595aabcf38a34137` |
| `kenney_impact/footstep_grass_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_grass_004.ogg | `086fd4ab3546a507ea5f5c759a9a10e535c95ade13705c238bc0eeffd7d4e8ba` |
| `kenney_impact/impactGeneric_light_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGeneric_light_000.ogg | `f0e982611e97512fee5f777986b67e8b435434b601f94992ec044f7e89fb5acb` |
| `kenney_impact/impactGeneric_light_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGeneric_light_001.ogg | `c3cd1c073d186ae8fa35788ba94de581f1826e7427a7bb26490b2695fac18efa` |
| `kenney_impact/impactGeneric_light_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGeneric_light_002.ogg | `d0bf60905b59ff630ffe01eb0edeeacd2504eaa8fb6523aeef7d2458b78264d3` |
| `kenney_impact/impactGeneric_light_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGeneric_light_003.ogg | `0e8896706130f6bc88cdf1f0157aaacdbe88dce86cf0330f9136e44eb1209e81` |
| `kenney_impact/impactGeneric_light_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGeneric_light_004.ogg | `f906fa3a37acc4372787b496efcedefa2856045d5ec9456a3bd6c303c0eabb41` |
| `kenney_impact/impactMetal_light_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMetal_light_000.ogg | `33b5e6e37c6e9d54e07bf5a89b12c76e879f40c1ea83cdd82714df1d6f9fec6d` |
| `kenney_impact/impactMetal_light_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMetal_light_001.ogg | `fba69c467ddd85da7b1d82e259f936b876d9ba6a3d6f1b24bdd10468e46bfe08` |
| `kenney_impact/impactMetal_light_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMetal_light_002.ogg | `25a96f90a9a1f88a531e824e126f0519504625e5635e65a72e4f31611428db29` |
| `kenney_impact/impactMetal_light_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMetal_light_003.ogg | `92d5db6bfc672d9dc1b4f390b2900504f013187fa36335472554fafefa9050b1` |
| `kenney_impact/impactMetal_light_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMetal_light_004.ogg | `9b1c35820fba507081261f19ab5f461f69a5e2627a7d91acdb73ca3cfc997979` |
| `kenney_impact/impactWood_light_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactWood_light_000.ogg | `eb45e35b4bed784d3f120de4afec4b0d6ac09d9e143cce8cfcb7d739e1b1f3c3` |
| `kenney_impact/impactWood_light_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactWood_light_001.ogg | `4b76bf3ccc8e60d19188f3165b778a7817786faa6887c55d9049bcbeef3b425f` |
| `kenney_impact/impactWood_light_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactWood_light_002.ogg | `b183cf7a5bd783817e0e4b82af34ac6658fa1927049089dadc8b15c2ecc771dc` |
| `kenney_impact/impactWood_light_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactWood_light_003.ogg | `cdfbe8af2fe7ff9ee28f337a0a989deee0f327620da456c8413644880e9d0004` |
| `kenney_impact/impactWood_light_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactWood_light_004.ogg | `e10009f67ddaeb3a59a3e1129cfc1615d84ba60ab578eae07e7092ac223f099c` |
| `kenney_impact/impactGlass_light_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGlass_light_000.ogg | `d750cf88097d0c3e69920e6e14496e1444e1a9da01aa4cca8f5ec8cb44c57b4f` |
| `kenney_impact/impactGlass_light_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGlass_light_001.ogg | `05e513fbd42829060eb37855f8c3866722ec5c39a8937c9bfde518cc609effa2` |
| `kenney_impact/impactGlass_light_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGlass_light_002.ogg | `710db7451bb7857b9140dfe6afe4621ea2188ad65eda3919c569d1bb285b933d` |
| `kenney_impact/impactGlass_light_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGlass_light_003.ogg | `765290ce32fa108c939a0dbd6fbacbcd05abde622b57b708eb8a64058ef4225a` |
| `kenney_impact/impactGlass_light_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactGlass_light_004.ogg | `f535b7cb7835400d8d28bcf9e1cf047ce3c0eb7a6456bdb1a4a27acbec1ed2cb` |
| `kenney_impact/impactSoft_medium_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_medium_000.ogg | `7d3ba0bb5e60a11b5d3e558c141303dcf494256675fbf753c0d252d2cf0481e3` |
| `kenney_impact/impactSoft_medium_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_medium_001.ogg | `7642a4fd43e547afe4f7adfadb3dabb681c0ff512f52c1674bae30a726841faf` |
| `kenney_impact/impactSoft_medium_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_medium_002.ogg | `5069e3571a77d7f7aae9ef71d0364aa245fb7d64a7c8cc9956f221d03088c089` |
| `kenney_impact/impactSoft_medium_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_medium_003.ogg | `5c4a1f35fde7e14046931da7bc3d1b23736541b7190ba107e08a379c4ca43cd6` |
| `kenney_impact/impactSoft_medium_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_medium_004.ogg | `b0a4dea90eed47accf50b768beff1166f2f1486fb139e4d025b2427637624bca` |
| `kenney_impact/impactSoft_heavy_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_heavy_000.ogg | `49e7ca88743fca974bb8676ea138b751cfd8f9033b5e7af8736c2a215d6edbc1` |
| `kenney_impact/impactSoft_heavy_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_heavy_001.ogg | `4d0096364ba9e46119d2ff6df493fdc101bd2e1efae061da5e5f77a53b3fdcb6` |
| `kenney_impact/impactSoft_heavy_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_heavy_002.ogg | `d130ae541951243d3f6ed963d0057450a445ffe117fbf9a084d34eb1635cb563` |
| `kenney_impact/impactSoft_heavy_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_heavy_003.ogg | `d00286a2dc62ee5cb4d42bf56120e7050a855f69e655fc1294410aadd337eba3` |
| `kenney_impact/impactSoft_heavy_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactSoft_heavy_004.ogg | `e008f0b6b14f62339c8fe9f9b45cbd6317ba4f66604c4899053b8017020a36f0` |
| `kenney_impact/impactPunch_medium_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPunch_medium_000.ogg | `486988aa2d6440ffc4c62a0e8ccf3c23673ba84424bd4723378d451b7255eb5c` |
| `kenney_impact/impactPunch_medium_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPunch_medium_001.ogg | `e71d23abcc3f10d9d6bc9615b2a431fff70b12333a5fcdd9964457564ace4349` |
| `kenney_impact/impactPunch_medium_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPunch_medium_002.ogg | `6492f9ccbc8d24dcef607bb1b48790b7870961474561f7fe5601e1c73a3018ef` |
| `kenney_impact/impactPunch_medium_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPunch_medium_003.ogg | `2d7c719c05999e0532f4384e1018e04cd916db715140bf16dee2dff3f820e908` |
| `kenney_impact/impactPunch_medium_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPunch_medium_004.ogg | `4a256878a3afb994ec9a4399336687748e68c7c136872c08c9c797d8c4e2464a` |
| `kenney_impact/impactPlank_medium_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPlank_medium_000.ogg | `8403cd7a043f0391574c88c55dd205743725b5363d2407f6de145f201690b68f` |
| `kenney_impact/impactPlank_medium_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPlank_medium_001.ogg | `d7c304319f8beac616231b62041fa8da74045b62d7155965516efb9b19303df4` |
| `kenney_impact/impactPlank_medium_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPlank_medium_002.ogg | `f6a14da45994229676b4f29e6a35f504b5c2ec2b8166fb1a3b1aa004bc6911ef` |
| `kenney_impact/impactPlank_medium_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPlank_medium_003.ogg | `0602a7b3eab5f53484f10fe775ee4204e7a2ba9703c886b302e012f7f6fab8de` |
| `kenney_impact/impactPlank_medium_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactPlank_medium_004.ogg | `6a51318c1c63821ea757622b57fafbf44c16c28129f6d39406a784260d87c447` |
| `kenney_impact/impactMining_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMining_000.ogg | `36b4ea107222d073c67ca64dde26944975609202d5090b2f2021213c1a7e35cd` |
| `kenney_impact/impactMining_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMining_001.ogg | `61235a18de3f3d92118235398222dbf51d448f1be70b1c8bc962b10b86f2d9c6` |
| `kenney_impact/impactMining_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMining_002.ogg | `059558ec751115ca6b1441e00f0adc837c1a3eeb0a066b109e0fd879fc5d0b0c` |
| `kenney_impact/impactMining_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMining_003.ogg | `4237fa2cd80364ad81cd0af44f67d7497f1c5edcc7bdb02cd22be2ba4580c83d` |
| `kenney_impact/impactMining_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/impactMining_004.ogg | `8ca3a99d85d845751ad8ce7b40509da58263a62e48cde70e5a30b5ccef4c9a3b` |
| `kenney_rpg/footstep00.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep00.ogg | `d0daf7bc4bee8633e6d20aad1f88798f2bd7b948be0f644c2f21c41a42c1e3c5` |
| `kenney_rpg/footstep01.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep01.ogg | `99514f67612034154c1a5f152b029fca130fdcd1594527257988ad9619052d34` |
| `kenney_rpg/footstep02.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep02.ogg | `4114ecb7bb1a939b65896fba95af09d1dc0fe89fabaf63c4d2934e60bfa35ac6` |
| `kenney_rpg/footstep03.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep03.ogg | `6cb4ddfd75ec915b3de63b742999b9a4cd647cd2f23180ddf33abc3962cc90b6` |
| `kenney_rpg/footstep04.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep04.ogg | `d5fc12c4eb2df153957c4726309297c5c5228c79b5a97c562e6ffdd0b7e4829b` |
| `kenney_rpg/footstep05.ogg` | https://media.githubusercontent.com/media/series-ai/jam-ready-assets/main/kenney-rpg-audio/audio/Audio/footstep05.ogg | `e9ff320f5b9645d9cd846437e393430d2c3454f6a3ffe94e44d876a9a4bbcf30` |
| `kenney_impact/footstep_wood_000.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_wood_000.ogg | `5f1c252942a220d658121bd9417448cd19649ded9fff2ff15f6e50899373ce8e` |
| `kenney_impact/footstep_wood_001.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_wood_001.ogg | `e4f68e1c9fd55b4dc8ca89ed2bbab6f200171bc54bdc18aa96b80d8e7336f462` |
| `kenney_impact/footstep_wood_002.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_wood_002.ogg | `9ff095b05cee5eec40b081defe3f0eef7232bb16d4865ce03b9f6dbab875cfdd` |
| `kenney_impact/footstep_wood_003.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_wood_003.ogg | `2a68a083daa9eda08fed0ea5da5280dfbe0de226196c576be02f95259dd139d9` |
| `kenney_impact/footstep_wood_004.ogg` | https://raw.githubusercontent.com/Gyrth/SketchyRenderer/main/Sounds/footstep_wood_004.ogg | `b33e0854e2b3f6b6492e25c25ef8f90447a332f7c6bb25dd02edced9581d3441` |

## Runtime soubory

| Soubor | Klíč | Zdroj (soubor@čas) | Licence | Úpravy | Délka | True peak | RMS / aktivní RMS | Velikost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `rifle_close_1.mp3` | `rifle_close` | ffsl:D_32P.wav@0.703s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 0.550 s | -3.0 dBFS | -30.8 / -22.5 dBFS | 11 KiB |
| `rifle_close_2.mp3` | `rifle_close` | ffsl:D_32P.wav@5.646s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 0.550 s | -3.0 dBFS | -30.8 / -22.6 dBFS | 11 KiB |
| `pistol_close_1.mp3` | `pistol_close` | ffsl:X_39P.wav@1.406s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 0.450 s | -4.0 dBFS | -33.4 / -21.8 dBFS | 9 KiB |
| `pistol_close_2.mp3` | `pistol_close` | ffsl:X_39P.wav@6.443s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 0.450 s | -4.0 dBFS | -33.3 / -22.0 dBFS | 10 KiB |
| `pistol_close_3.mp3` | `pistol_close` | ffsl:X_39P.wav@10.659s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 0.450 s | -4.0 dBFS | -33.2 / -22.4 dBFS | 9 KiB |
| `rifle_distant_1.mp3` | `rifle_distant` | ffsl:D_24P.wav@0.548s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.500 s | -6.0 dBFS | -33.6 / -28.9 dBFS | 12 KiB |
| `rifle_distant_2.mp3` | `rifle_distant` | ffsl:D_24P.wav@3.909s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.500 s | -6.0 dBFS | -34.3 / -29.5 dBFS | 12 KiB |
| `pistol_distant_1.mp3` | `pistol_distant` | ffsl:X_31P.wav@1.084s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.300 s | -6.0 dBFS | -35.8 / -24.9 dBFS | 9 KiB |
| `pistol_distant_2.mp3` | `pistol_distant` | ffsl:X_31P.wav@5.242s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.300 s | -6.0 dBFS | -35.8 / -25.2 dBFS | 9 KiB |
| `rifle_tail_1.mp3` | `rifle_tail` | ffsl:D_24P.wav@0.648s (reflections only) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.450 s | -9.0 dBFS | -40.1 / -37.7 dBFS | 16 KiB |
| `rifle_tail_2.mp3` | `rifle_tail` | ffsl:D_24P.wav@4.009s (reflections only) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.450 s | -9.0 dBFS | -39.8 / -37.6 dBFS | 16 KiB |
| `pistol_tail_1.mp3` | `pistol_tail` | ffsl:X_31P.wav@1.174s (reflections only) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3, převzorkování na 44,1 kHz | 1.200 s | -9.0 dBFS | -47.1 / -44.5 dBFS | 13 KiB |
| `rifle_mag_out.mp3` | `rifle_mag_out` | springy:assaultriflereload1_0.wav@0.12-0.52s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.371 s | -10.0 dBFS | -33.1 / -30.8 dBFS | 4 KiB |
| `rifle_mag_in.mp3` | `rifle_mag_in` | springy:assaultriflereload1_0.wav@1.00-1.24s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.199 s | -10.0 dBFS | -30.5 / -30.4 dBFS | 3 KiB |
| `rifle_bolt_release.mp3` | `rifle_bolt_release` | lfa:equipment_clicks3.wav@18.026-18.21s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.135 s | -10.0 dBFS | -27.7 / -26.0 dBFS | 2 KiB |
| `rifle_charge_pull.mp3` | `rifle_charge_pull` | lfa:equipment_clicks3.wav@1.449-1.707s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.230 s | -11.0 dBFS | -28.8 / -27.2 dBFS | 3 KiB |
| `rifle_charge_release.mp3` | `rifle_charge_release` | lfa:equipment_clicks3.wav@0.854-1.094s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.213 s | -10.0 dBFS | -27.9 / -24.6 dBFS | 3 KiB |
| `pistol_mag_out.mp3` | `pistol_mag_out` | springy:gunreload1.wav@0.08-0.32s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.196 s | -11.0 dBFS | -33.2 / -32.6 dBFS | 3 KiB |
| `pistol_mag_in.mp3` | `pistol_mag_in` | springy:gunreload1.wav@0.64-0.82s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.139 s | -11.0 dBFS | -33.9 / -32.6 dBFS | 2 KiB |
| `pistol_slide_pull.mp3` | `pistol_slide_pull` | lfa:equipment_clicks3.wav@18.807-19.08s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.268 s | -12.0 dBFS | -34.2 / -33.7 dBFS | 4 KiB |
| `pistol_slide_release.mp3` | `pistol_slide_release` | lfa:equipment_clicks3.wav@16.292-16.448s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.153 s | -10.0 dBFS | -28.8 / -27.3 dBFS | 2 KiB |
| `rifle_dry.mp3` | `rifle_dry` | lfa:equipment_clicks3.wav@0.186-0.347s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.139 s | -14.0 dBFS | -33.3 / -32.3 dBFS | 2 KiB |
| `pistol_dry.mp3` | `pistol_dry` | lfa:equipment_clicks3.wav@5.085-5.176s | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.070 s | -14.0 dBFS | -35.9 / -34.1 dBFS | 1 KiB |
| `switch_cloth_1.mp3` | `switch_cloth` | kenney_rpg:cloth1.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.595 s | -16.0 dBFS | -39.2 / -38.1 dBFS | 6 KiB |
| `switch_cloth_2.mp3` | `switch_cloth` | kenney_rpg:cloth2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.362 s | -16.0 dBFS | -36.3 / -34.9 dBFS | 4 KiB |
| `switch_cloth_3.mp3` | `switch_cloth` | kenney_rpg:cloth3.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.463 s | -16.0 dBFS | -35.3 / -34.4 dBFS | 4 KiB |
| `switch_draw_rifle.mp3` | `switch_draw_rifle` | kenney_rpg:beltHandle1.ogg + metalLatch.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.421 s | -12.0 dBFS | -36.2 / -33.7 dBFS | 5 KiB |
| `switch_draw_pistol.mp3` | `switch_draw_pistol` | kenney_rpg:handleSmallLeather.ogg + metalClick.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.350 s | -13.0 dBFS | -36.0 / -34.6 dBFS | 4 KiB |
| `step_concrete_1.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneL1.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -5.4 dBFS | -25.1 / -24.0 dBFS | 3 KiB |
| `step_concrete_2.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneL2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -5.5 dBFS | -24.8 / -24.0 dBFS | 3 KiB |
| `step_concrete_3.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneL3.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -7.3 dBFS | -24.6 / -24.0 dBFS | 3 KiB |
| `step_concrete_4.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneR1.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -4.7 dBFS | -24.7 / -24.0 dBFS | 4 KiB |
| `step_concrete_5.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneR2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -5.8 dBFS | -24.7 / -24.0 dBFS | 3 KiB |
| `step_concrete_6.mp3` | `step_concrete` | fantozzi:Fantozzi-StoneR3.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -5.5 dBFS | -24.7 / -24.0 dBFS | 3 KiB |
| `step_dirt_1.mp3` | `step_dirt` | fantozzi:Fantozzi-SandL1.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.320 s | -1.8 dBFS | -25.0 / -24.0 dBFS | 4 KiB |
| `step_dirt_2.mp3` | `step_dirt` | fantozzi:Fantozzi-SandL2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.316 s | -1.4 dBFS | -24.7 / -24.0 dBFS | 4 KiB |
| `step_dirt_3.mp3` | `step_dirt` | fantozzi:Fantozzi-SandL3.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.298 s | -1.0 dBFS | -27.5 / -27.2 dBFS | 4 KiB |
| `step_dirt_4.mp3` | `step_dirt` | fantozzi:Fantozzi-SandR1.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.320 s | -1.0 dBFS | -25.7 / -24.8 dBFS | 4 KiB |
| `step_dirt_5.mp3` | `step_dirt` | fantozzi:Fantozzi-SandR2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.320 s | -1.0 dBFS | -26.0 / -25.2 dBFS | 4 KiB |
| `step_dirt_6.mp3` | `step_dirt` | fantozzi:Fantozzi-SandR3.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.320 s | -1.4 dBFS | -24.4 / -24.0 dBFS | 4 KiB |
| `step_gravel_1.mp3` | `step_gravel` | cdogs:gravel/0.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.189 s | -4.4 dBFS | -24.5 / -24.0 dBFS | 3 KiB |
| `step_gravel_2.mp3` | `step_gravel` | cdogs:gravel/1.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.106 s | -9.9 dBFS | -24.5 / -24.0 dBFS | 2 KiB |
| `step_gravel_3.mp3` | `step_gravel` | cdogs:gravel/2.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.226 s | -7.8 dBFS | -24.6 / -24.0 dBFS | 3 KiB |
| `step_gravel_4.mp3` | `step_gravel` | cdogs:gravel/3.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.158 s | -5.8 dBFS | -25.0 / -24.0 dBFS | 2 KiB |
| `step_gravel_5.mp3` | `step_gravel` | cdogs:gravel/4.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.244 s | -4.7 dBFS | -24.9 / -24.0 dBFS | 3 KiB |
| `step_gravel_6.mp3` | `step_gravel` | cdogs:gravel/5.ogg | CC0 1.0 | střih, HP/LP filtr, fade, normalizace, MP3 | 0.229 s | -6.3 dBFS | -24.8 / -24.0 dBFS | 3 KiB |
| `step_grass_1.mp3` | `step_grass` | kenney_impact:footstep_grass_000.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.220 s | -8.4 dBFS | -30.8 / -24.0 dBFS | 2 KiB |
| `step_grass_2.mp3` | `step_grass` | kenney_impact:footstep_grass_001.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.220 s | -4.9 dBFS | -26.6 / -24.0 dBFS | 2 KiB |
| `step_grass_3.mp3` | `step_grass` | kenney_impact:footstep_grass_002.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.220 s | -5.2 dBFS | -27.2 / -24.0 dBFS | 2 KiB |
| `step_grass_4.mp3` | `step_grass` | kenney_impact:footstep_grass_003.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.220 s | -7.9 dBFS | -30.8 / -24.0 dBFS | 2 KiB |
| `step_grass_5.mp3` | `step_grass` | kenney_impact:footstep_grass_004.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.220 s | -9.0 dBFS | -30.8 / -24.0 dBFS | 2 KiB |
| `step_wood_1.mp3` | `step_wood` | kenney_rpg:footstep00.ogg + kenney_impact:footstep_wood_000.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.224 s | -6.2 dBFS | -27.1 / -24.0 dBFS | 2 KiB |
| `step_wood_2.mp3` | `step_wood` | kenney_rpg:footstep01.ogg + kenney_impact:footstep_wood_001.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.250 s | -7.0 dBFS | -26.8 / -24.0 dBFS | 3 KiB |
| `step_wood_3.mp3` | `step_wood` | kenney_rpg:footstep02.ogg + kenney_impact:footstep_wood_002.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.230 s | -4.9 dBFS | -25.7 / -24.0 dBFS | 3 KiB |
| `step_wood_4.mp3` | `step_wood` | kenney_rpg:footstep03.ogg + kenney_impact:footstep_wood_003.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.254 s | -7.4 dBFS | -26.7 / -24.0 dBFS | 3 KiB |
| `step_wood_5.mp3` | `step_wood` | kenney_rpg:footstep04.ogg + kenney_impact:footstep_wood_004.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.260 s | -9.0 dBFS | -26.3 / -24.0 dBFS | 3 KiB |
| `step_wood_6.mp3` | `step_wood` | kenney_rpg:footstep05.ogg + kenney_impact:footstep_wood_000.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.260 s | -8.1 dBFS | -28.0 / -24.0 dBFS | 3 KiB |
| `step_metal_1.mp3` | `step_metal` | cdogs:metal/0.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -5.4 dBFS | -27.3 / -24.0 dBFS | 3 KiB |
| `step_metal_2.mp3` | `step_metal` | cdogs:metal/1.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -4.1 dBFS | -25.2 / -24.0 dBFS | 3 KiB |
| `step_metal_3.mp3` | `step_metal` | cdogs:metal/2.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.300 s | -3.9 dBFS | -27.6 / -24.0 dBFS | 3 KiB |
| `step_metal_4.mp3` | `step_metal` | cdogs:metal/3.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.181 s | -8.1 dBFS | -25.3 / -24.0 dBFS | 2 KiB |
| `step_metal_5.mp3` | `step_metal` | cdogs:metal/4.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.140 s | -8.6 dBFS | -25.3 / -24.0 dBFS | 2 KiB |
| `step_metal_6.mp3` | `step_metal` | cdogs:metal/5.ogg | CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.286 s | -6.5 dBFS | -26.0 / -24.0 dBFS | 3 KiB |
| `jump_gear_1.mp3` | `jump_gear` | kenney_rpg:cloth4.ogg + beltHandle2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.527 s | -16.0 dBFS | -38.9 / -37.7 dBFS | 6 KiB |
| `jump_gear_2.mp3` | `jump_gear` | kenney_rpg:clothBelt2.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.753 s | -16.0 dBFS | -40.1 / -38.0 dBFS | 9 KiB |
| `traverse_gear_1.mp3` | `traverse_gear` | kenney_rpg:clothBelt.ogg | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.723 s | -15.0 dBFS | -42.1 / -40.8 dBFS | 10 KiB |
| `land_thump_1.mp3` | `land_thump` | kenney_impact:impactSoft_heavy_000.ogg (low-passed 500 Hz) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.280 s | -12.0 dBFS | -25.7 / -24.2 dBFS | 2 KiB |
| `land_thump_2.mp3` | `land_thump` | kenney_impact:impactSoft_heavy_001.ogg (low-passed 500 Hz) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.280 s | -12.0 dBFS | -25.3 / -24.0 dBFS | 2 KiB |
| `impact_concrete_1.mp3` | `impact_concrete` | kenney_impact:impactGeneric_light_000.ogg + synth crack/debris | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.222 s | -8.0 dBFS | -30.1 / -26.6 dBFS | 4 KiB |
| `impact_concrete_2.mp3` | `impact_concrete` | kenney_impact:impactGeneric_light_001.ogg + synth crack/debris | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.222 s | -8.0 dBFS | -33.8 / -30.8 dBFS | 4 KiB |
| `impact_concrete_3.mp3` | `impact_concrete` | kenney_impact:impactGeneric_light_002.ogg + synth crack/debris | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.222 s | -8.0 dBFS | -32.9 / -30.0 dBFS | 3 KiB |
| `impact_metal_1.mp3` | `impact_metal` | kenney_impact:impactMetal_light_000.ogg + synth ping | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.306 s | -8.0 dBFS | -31.1 / -29.7 dBFS | 2 KiB |
| `impact_metal_2.mp3` | `impact_metal` | kenney_impact:impactMetal_light_001.ogg + synth ping | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.301 s | -8.0 dBFS | -30.6 / -29.1 dBFS | 2 KiB |
| `impact_metal_3.mp3` | `impact_metal` | kenney_impact:impactMetal_light_002.ogg + synth ping | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.301 s | -8.0 dBFS | -29.4 / -27.8 dBFS | 2 KiB |
| `impact_wood_1.mp3` | `impact_wood` | kenney_impact:impactWood_light_000.ogg + synth splinters | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.160 s | -8.0 dBFS | -28.8 / -24.5 dBFS | 2 KiB |
| `impact_wood_2.mp3` | `impact_wood` | kenney_impact:impactWood_light_001.ogg + synth splinters | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.160 s | -8.0 dBFS | -30.4 / -25.4 dBFS | 2 KiB |
| `impact_wood_3.mp3` | `impact_wood` | kenney_impact:impactWood_light_002.ogg + synth splinters | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.160 s | -8.0 dBFS | -27.7 / -24.3 dBFS | 2 KiB |
| `impact_dirt_1.mp3` | `impact_dirt` | kenney_impact:impactSoft_medium_000.ogg + synth dirt spray | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.221 s | -9.0 dBFS | -26.4 / -24.0 dBFS | 2 KiB |
| `impact_dirt_2.mp3` | `impact_dirt` | kenney_impact:impactSoft_medium_001.ogg + synth dirt spray | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.221 s | -9.0 dBFS | -25.7 / -23.2 dBFS | 2 KiB |
| `impact_dirt_3.mp3` | `impact_dirt` | kenney_impact:impactSoft_medium_002.ogg + synth dirt spray | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.221 s | -9.0 dBFS | -27.5 / -24.7 dBFS | 3 KiB |
| `impact_glass_1.mp3` | `impact_glass` | kenney_impact:impactGlass_light_000.ogg + synth shards | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.352 s | -8.0 dBFS | -31.6 / -28.2 dBFS | 3 KiB |
| `impact_glass_2.mp3` | `impact_glass` | kenney_impact:impactGlass_light_001.ogg + synth shards | CC0 1.0 (volné dílo) + **procedurální vrstva — prozatímní** | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.352 s | -8.0 dBFS | -34.2 / -30.8 dBFS | 3 KiB |
| `impact_flesh_1.mp3` | `impact_flesh` | kenney_impact:impactPunch_medium_000.ogg (low-passed, shortened) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.160 s | -12.0 dBFS | -24.2 / -22.7 dBFS | 2 KiB |
| `impact_flesh_2.mp3` | `impact_flesh` | kenney_impact:impactPunch_medium_001.ogg (low-passed, shortened) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.160 s | -12.0 dBFS | -24.8 / -23.1 dBFS | 2 KiB |
| `impact_flesh_3.mp3` | `impact_flesh` | kenney_impact:impactPunch_medium_002.ogg (low-passed, shortened) | CC0 1.0 (volné dílo) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.160 s | -12.0 dBFS | -24.5 / -23.6 dBFS | 2 KiB |
| `nearmiss_crack_1.mp3` | `nearmiss_crack` | procedural synthesis (N-wave + wake) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.161 s | -6.0 dBFS | -27.7 / -26.9 dBFS | 3 KiB |
| `nearmiss_crack_2.mp3` | `nearmiss_crack` | procedural synthesis (N-wave + wake) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.161 s | -6.0 dBFS | -28.1 / -27.4 dBFS | 3 KiB |
| `nearmiss_crack_3.mp3` | `nearmiss_crack` | procedural synthesis (N-wave + wake) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.161 s | -6.0 dBFS | -27.4 / -26.8 dBFS | 3 KiB |
| `nearmiss_whiz_1.mp3` | `nearmiss_whiz` | procedural synthesis (weak N-wave + Doppler wake) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.220 s | -8.0 dBFS | -25.9 / -25.3 dBFS | 3 KiB |
| `nearmiss_whiz_2.mp3` | `nearmiss_whiz` | procedural synthesis (weak N-wave + Doppler wake) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.220 s | -8.0 dBFS | -25.6 / -25.0 dBFS | 3 KiB |
| `casing_rifle_1.mp3` | `casing_rifle` | procedural synthesis (modal brass) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.360 s | -18.0 dBFS | -38.8 / -37.1 dBFS | 3 KiB |
| `casing_rifle_2.mp3` | `casing_rifle` | procedural synthesis (modal brass) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.360 s | -18.0 dBFS | -37.6 / -36.2 dBFS | 3 KiB |
| `casing_pistol_1.mp3` | `casing_pistol` | procedural synthesis (modal brass) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.300 s | -18.0 dBFS | -34.8 / -33.9 dBFS | 3 KiB |
| `casing_pistol_2.mp3` | `casing_pistol` | procedural synthesis (modal brass) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 0.300 s | -18.0 dBFS | -36.5 / -36.0 dBFS | 3 KiB |
| `amb_wind_loop.mp3` | `amb_wind` | procedural synthesis (loopable wind) | **procedurální syntéza — prozatímní** (vlastní) | střih, HP/LP filtr, fade, normalizace, MP3, syntéza | 16.000 s | -17.9 dBFS | -36.0 / -36.0 dBFS | 167 KiB |
| `amb_bird_1.mp3` | `amb_bird` | librosa:robin.hq.ogg@0.05-0.78s | CC BY 4.0 (uvést autora) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.730 s | -18.2 dBFS | -36.0 / -34.0 dBFS | 4 KiB |
| `amb_bird_2.mp3` | `amb_bird` | librosa:robin.hq.ogg@0.78-1.26s | CC BY 4.0 (uvést autora) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.480 s | -19.3 dBFS | -35.0 / -34.0 dBFS | 3 KiB |
| `amb_bird_3.mp3` | `amb_bird` | librosa:robin.hq.ogg@1.26-2.25s | CC BY 4.0 (uvést autora) | střih, HP/LP filtr, fade, normalizace, MP3 | 0.990 s | -20.5 dBFS | -35.7 / -34.0 dBFS | 5 KiB |

Celkem 98 souborů, 620 KiB.

## Syntéza (prozatímní) — co a proč

- **Vítr** (`amb_wind_loop`): žádná čistě licencovaná nahrávka větru nebyla dosažitelná. Smyčkovatelný šum z náhodné fáze spektra (kruhová IFFT = bezešvá smyčka), sklon −4,5 dB/okt od 100 Hz, poryvy s celočíselným počtem period na smyčku, stereo z nezávislého šumu, jemné šumění listí.
- **Průlet střely** (`nearmiss_crack`, `nearmiss_whiz`): N-vlna rázové vlny nadzvukové střely (délka 0,13–0,18 ms podle Whithamova vztahu pro 5,56 mm na 1–3 m), odraz od země 1,8–2,9 ms, turbulentní „zip“ s klesající frekvencí (Doppler), slabý odraz od terénu; 9 mm = slabá N-vlna + výraznější „vzum“.
- **Nábojnice** (`casing_*`): modální syntéza tenké mosazné trubky (poměry 1 : 2,76 : 5,40), 2–4 odskoky s restitucí ~0,5.
- **Vrstvy zásahů** (`impact_*` kromě `impact_flesh`): Kenney CC0 tělo materiálu + syntetický prask, granulární úlomky, sprška hlíny, střepy skla.

Náhrada za finální assety: nahrávky větru a průletů střel (CC0/CC BY) nebo vlastní nahrávky.
