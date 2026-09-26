# IRON VALLEY — stav projektu

Tento soubor čti jako první při každém pokračování práce.

| Položka | Hodnota |
| --- | --- |
| Aktuální fáze | A — dostupnost prostředí (Unreal zablokovaný), B-příprava — ověření pipeline assetů v Blenderu |
| Startovací mapa | zatím neexistuje |
| Engine | Unreal Engine 5 — **není k dispozici** (viz tabulka níže) |
| Blender | 4.5.14 LTS jako Python modul `bpy` (PyPI), bez GUI |
| Higgsfield | nepřipojen |
| Datum | 2026-09-26 |

## Prostředí, ve kterém se pracuje

Vzdálený cloudový kontejner (Ubuntu 24.04.4 LTS, Linux 6.18, x86_64), 4× Intel Xeon @ 2,1 GHz, 15 GiB RAM, bez swapu,
cca 29 GB volného disku, **bez GPU** (`/dev/dri` chybí, `nvidia-smi` chybí). Síťový přístup omezený politikou prostředí.

## Tabulka dostupnosti (ověřeno 2026-09-26)

| Oblast | Stav | Důkaz / překážka |
| --- | --- | --- |
| Unreal Editor | CHYBÍ | Není nainstalován. `www.unrealengine.com` a `dev.epicgames.com` vrací 403 (síťová politika), `github.com/EpicGames/UnrealEngine` vyžaduje propojený Epic účet. Stroj nemá GPU a má jen ~29 GB volného disku. |
| Build UE (C++ / UBT) | CHYBÍ | `clang 18`, `gcc`, `cmake` jsou k dispozici, ale bez hlaviček enginu a UnrealBuildTool nelze UE modul zkompilovat. Čisté C++ bez UE kompilovat lze. |
| Blender | OVĚŘENO | `pip install bpy==4.5.*` → `bpy 4.5.14 LTS`; testovací render Cycles (CPU) 320×240 za 0,73 s; export FBX (`io_scene_fbx`) i GLB (`io_scene_gltf2`) proběhl. GUI Blenderu není; `download.blender.org` je blokován. |
| Higgsfield | CHYBÍ | V relaci není žádný konektor (`ListConnectors` → prázdné), `higgsfield.ai` vrací 403 (síťová politika), v registru konektorů nebyl nalezen. |
| Import assetů do UE | CHYBÍ | Závisí na Unreal Editoru. |
| Render (kontrola vzhledu) | OVĚŘENO | Cycles CPU render do PNG, obrázky umím prohlížet. Render z Blenderu **neprokazuje** vzhled ve hře. |
| Místní spuštění hry (UE) | CHYBÍ | Bez Unreal Editoru nelze PIE ani Standalone. |
| Prohlížečový test | OVĚŘENO (jen WebGL) | Headless Chromium (Playwright 1.56.1) → WebGL 2.0 přes SwiftShader (softwarově). Pixel Streaming: CHYBÍ (vyžaduje běžící UE aplikaci). |

`localhost` tohoto kontejneru není `localhost` uživatele. Pro náhled uživateli lze použít jen skutečně podporovanou cestu
(soukromý odkaz na Artifact na claude.ai) nebo přesný postup místního spuštění na jeho stroji.

### Nejmenší kroky k odblokování

1. **Unreal:** spustit tuto práci na počítači s nainstalovaným UE 5.x a GPU (Claude Code lokálně / desktopová aplikace), nebo
   v self-hosted prostředí s GPU, UE5 a povoleným přístupem na domény Epic. V tomto cloudovém kontejneru UE5 provozovat nelze.
2. **Higgsfield:** připojit konektor Higgsfield na claude.ai a v nastavení prostředí povolit síťový přístup na domény, ze kterých
   se stahují výstupy generací (a schválit kreditový rozpočet).
3. **Blender GUI:** není potřeba; pipeline běží skripty přes `bpy`.

## Rozhodnutí uživatele (2026-09-26)

- **Hybrid:** hratelná verze pro prohlížeč (three.js/WebGL) z assetů z Blenderu, testovaná zde a předaná jako soukromý odkaz;
  paralelně příprava projektu UE5 (FBX, C++ zdroj, importní skripty) — ten zůstane nezkompilovaný a NOT TESTED.
- **Higgsfield:** pokračovat bez něj; HF-01 = BLOCKED, dokud nebude připojen.
- Technická rozhodnutí a adresáře: `Docs/ARCHITECTURE.md`. Původní zadání: `Docs/zadani/`.

## Hotovo

- Kontrola prostředí a tabulka dostupnosti (výše).

## Známé vady / otevřené body

- P0 (vnější blokátor): Unreal Engine 5 není v prostředí dostupný → hra v UE nemůže být spuštěna ani testována.
- HF-01: BLOCKED — Higgsfield nepřipojen.

## Další krok

Ověřit jeden kompletní průchod pipeline assetu (puška: model → UV → materiály → bake textur → export FBX/GLB → kontrolní rendery
→ zpětný import) a rozhodnout s uživatelem náhradní cestu ke spustitelné verzi.
