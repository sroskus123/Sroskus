#!/usr/bin/env python3
"""Writes Shared/audio/SOURCES.md from Tools/audio/sources.json (pinned third-party files, licence evidence)
and Web/src/data/audio_bank.json (runtime files + measured stats written by build_audio.py).

    python3 Tools/audio/write_sources.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(ROOT, 'Shared', 'audio', 'SOURCES.md')

LIC_CS = {
    'CC0-1.0': 'CC0 1.0 (volné dílo)',
    'CC-BY-4.0': 'CC BY 4.0 (uvést autora)',
    'CC-BY-3.0': 'CC BY 3.0 (uvést autora)',
}

HEADER = """# IRON VALLEY — zvuky: zdroje, licence, úpravy

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

"""


def main():
    src = json.load(open(os.path.join(HERE, 'sources.json'), encoding='utf8'))
    bank = json.load(open(os.path.join(ROOT, 'Web', 'src', 'data', 'audio_bank.json'), encoding='utf8'))
    files_by_path = {f['path']: f for f in src['files']}
    out = [HEADER]
    out.append('| Balíček | Autor | Licence | Stránka | Doklad licence / ověření bajtů |\n| --- | --- | --- | --- | --- |\n')
    for pid, p in src['packs'].items():
        lic = LIC_CS.get(p['licence'], p['licence'])
        out.append(f"| `{pid}` — {p['title']} | {p['author']} | {lic} | {p['page']} | {p['evidence']} |\n")
    out.append('\nC-Dogs kroky (`cdogs`) mají licenci po površích (`license.txt` ve složce): štěrk = Ali_6868, CC0 1.0;'
               ' kov = Eelke, CC BY 4.0 (OGA text balíčku uvádí CC BY 3.0 — obojí jen vyžaduje uvést autora); úprava'
               ' congusbongus (OpenGameArt „Footsteps on different surfaces“, CC BY 3.0).\n')

    out.append('\n## Staženo (připnuto SHA-256)\n\n| Soubor v `_src/` | URL | SHA-256 |\n| --- | --- | --- |\n')
    for f in src['files']:
        extra = f" — {f['author']}, {f['licence']}, {f['upstream']}" if f.get('author') else ''
        out.append(f"| `{f['path']}`{extra} | {f['url']} | `{f['sha256']}` |\n")

    out.append('\n## Runtime soubory\n\n| Soubor | Klíč | Zdroj (soubor@čas) | Licence | Úpravy | Délka | True peak | RMS / aktivní RMS | Velikost |\n'
               '| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n')
    total = 0
    for name, m in bank['files'].items():
        total += m['bytes']
        srcs = m['source']
        if m['synth'] and srcs.startswith('procedural'):
            lic = '**procedurální syntéza — prozatímní** (vlastní)'
        else:
            lic_parts = []
            for pid, pk in src['packs'].items():
                if srcs.startswith(pid + ':') or f' {pid}:' in srcs or f'+ {pid}:' in srcs:
                    if pid == 'cdogs':
                        surf = 'gravel' if 'gravel' in srcs else 'metal'
                        lic_parts.append('CC0 1.0' if surf == 'gravel' else 'CC BY 4.0 (Eelke) + CC BY 3.0 (congusbongus)')
                    else:
                        lic_parts.append(LIC_CS.get(pk['licence'], pk['licence']))
            lic = ' + '.join(dict.fromkeys(lic_parts)) or '?'
            if m['synth']:
                lic += ' + **procedurální vrstva — prozatímní**'
        mods = 'střih, HP/LP filtr, fade, normalizace, MP3' + (', převzorkování na 44,1 kHz' if 'ffsl' in srcs else '') + (', syntéza' if m['synth'] else '')
        out.append(f"| `{name}` | `{m['key']}` | {srcs} | {lic} | {mods} | {m['duration']:.3f} s | {m['truePeakDb']} dBFS | {m['rmsDb']} / {m['activeRmsDb']} dBFS | {m['bytes'] // 1024} KiB |\n")
    out.append(f"\nCelkem {len(bank['files'])} souborů, {total / 1024:.0f} KiB.\n")
    out.append('\n## Syntéza (prozatímní) — co a proč\n\n'
               '- **Vítr** (`amb_wind_loop`): žádná čistě licencovaná nahrávka větru nebyla dosažitelná. Smyčkovatelný šum z náhodné fáze'
               ' spektra (kruhová IFFT = bezešvá smyčka), sklon −4,5 dB/okt od 100 Hz, poryvy s celočíselným počtem period na smyčku,'
               ' stereo z nezávislého šumu, jemné šumění listí.\n'
               '- **Průlet střely** (`nearmiss_crack`, `nearmiss_whiz`): N-vlna rázové vlny nadzvukové střely (délka 0,13–0,18 ms podle'
               ' Whithamova vztahu pro 5,56 mm na 1–3 m), odraz od země 1,8–2,9 ms, turbulentní „zip“ s klesající frekvencí (Doppler),'
               ' slabý odraz od terénu; 9 mm = slabá N-vlna + výraznější „vzum“.\n'
               '- **Nábojnice** (`casing_*`): modální syntéza tenké mosazné trubky (poměry 1 : 2,76 : 5,40), 2–4 odskoky s restitucí ~0,5.\n'
               '- **Vrstvy zásahů** (`impact_*` kromě `impact_flesh`): Kenney CC0 tělo materiálu + syntetický prask, granulární úlomky,'
               ' sprška hlíny, střepy skla.\n'
               '\nNáhrada za finální assety: nahrávky větru a průletů střel (CC0/CC BY) nebo vlastní nahrávky.\n')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf8') as fh:
        fh.write(''.join(out))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
