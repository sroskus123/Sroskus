// Menus (DOM, Czech): title, loadout, pause, settings (incl. key rebinding and master volume), controls,
// results and quit. Only the active screen is in the DOM, so there is exactly one primary button
// (.iv-btn-primary) at a time. While a menu is open the game input is disabled and the cursor is free.

import { keyLabel } from '../player/input.js';
import { REBINDABLE } from '../player/bindingsStore.js';
import audioConfig from '../data/audio.json' with { type: 'json' };
import { ATTACHMENTS, IRONS, opticChoices, opticName } from '../weapons/optics.js';
import { loadTitleArt, loadUiFonts } from './uiAssets.js';

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

function button(text, cls, onClick, name) {
  const b = el('button', `iv-btn ${cls || ''}`.trim(), text);
  b.type = 'button';
  if (name) b.dataset.action = name;
  b.addEventListener('click', (e) => {
    e.preventDefault();
    onClick(e);
  });
  return b;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs = {}, text) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

/**
 * IRON VALLEY logo as inline SVG: two lines stretched to the mockup's proportions (textLength), worn paint made by
 * a turbulence filter that erodes the letters. Inline markup fetches nothing, so no CSP directive applies; if a
 * browser ignores the filter the logo is simply clean.
 */
function logoSvg() {
  const s = svg('svg', { viewBox: '0 0 410 226', class: 'iv-logo-svg', 'aria-hidden': 'true', focusable: 'false' });
  const defs = svg('defs');
  const grad = svg('linearGradient', { id: 'iv-logo-fill', x1: 0, y1: 0, x2: 0, y2: 1 });
  grad.append(svg('stop', { offset: 0, 'stop-color': '#f3eee5' }), svg('stop', { offset: 1, 'stop-color': '#d6cebf' }));
  const f = svg('filter', { id: 'iv-logo-wear', x: 0, y: 0, width: 1, height: 1, 'color-interpolation-filters': 'sRGB' });
  f.append(
    // fine chips
    svg('feTurbulence', { type: 'fractalNoise', baseFrequency: 0.8, numOctaves: 2, seed: 11, result: 'fine' }),
    svg('feColorMatrix', { in: 'fine', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  16 0 0 0 -11.3', result: 'chips' }),
    // larger worn patches
    svg('feTurbulence', { type: 'fractalNoise', baseFrequency: 0.045, numOctaves: 3, seed: 5, result: 'coarse' }),
    svg('feColorMatrix', { in: 'coarse', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  30 0 0 0 -23.4', result: 'patches' }),
    svg('feComposite', { in: 'chips', in2: 'patches', operator: 'arithmetic', k1: 0, k2: 1, k3: 1, k4: 0, result: 'wear' }),
    svg('feComposite', { in: 'SourceGraphic', in2: 'wear', operator: 'out' }),
  );
  defs.append(grad, f);
  const g = svg('g', { fill: 'url(#iv-logo-fill)', filter: 'url(#iv-logo-wear)' });
  g.append(
    svg('text', { x: 1, y: 100, 'font-size': 140, 'letter-spacing': -7, textLength: 280, lengthAdjust: 'spacingAndGlyphs' }, 'IRON'),
    svg('text', { x: 1, y: 222, 'font-size': 140, 'letter-spacing': -7, textLength: 404, lengthAdjust: 'spacingAndGlyphs' }, 'VALLEY'),
  );
  s.append(defs, g);
  return s;
}

// screens opened from the title or pause menu that return to where they were opened from
const SUB_SCREENS = new Set(['settings', 'controls', 'quit', 'credits']);

const CONTROL_ROWS = ['moveForward', 'moveBackward', 'moveLeft', 'moveRight', 'fire', 'aim', 'reload', 'sprint', 'walk', 'crouch', 'jump', 'interact', 'swapOptic', 'weapon1', 'weapon2', 'menu'];

export class Menus {
  /**
   * @param {HTMLElement} root
   * @param {object} o { settings, bindingsStore, levels: () => [{id,name}], currentLevel: () => id,
   *   weaponsData, teamsData, rulesInfo: () => {...}, actions: { start, practice, deploy, resume, leave,
   *   newRound, changeLoadout, mainMenu, selectLevel, quit, gesture } }
   */
  constructor(root, o) {
    this.root = root;
    this.o = o;
    this.menu = el('div', 'iv-menu');
    this.menu.setAttribute('role', 'dialog');
    this.menu.setAttribute('aria-modal', 'true');
    this.panel = el('div', 'iv-panel');
    // title / loading background (CSS shows it only on those screens); drawn from an ImageBitmap, no image URL
    this.art = el('canvas', 'iv-title-art');
    this.art.setAttribute('aria-hidden', 'true');
    this.art.width = this.art.height = 1;
    this.menu.append(this.art, this.panel);
    root.append(this.menu);
    loadUiFonts();
    loadTitleArt().then((bitmap) => {
      if (!bitmap) return;
      this.art.width = bitmap.width;
      this.art.height = bitmap.height;
      this.art.getContext('2d').drawImage(bitmap, 0, 0);
      this.art.classList.add('iv-ready');
    });
    // every click in a menu is a user gesture (audio unlock etc.)
    this.panel.addEventListener('click', () => o.actions.gesture && o.actions.gesture(), true);
    this.screen = null;
    this.parent = null; // screen to return to from settings / controls
    this.statusText = '';
    this.optic = ATTACHMENTS.loadoutDefault.optic;
    this.spare = ATTACHMENTS.loadoutDefault.spare ?? null;
    this.armoryData = null;
    this.capturing = null;
    this._onCaptureKey = (e) => this._captureKey(e);
    this._onCaptureMouse = (e) => this._captureMouse(e);
    this.results = null;
  }

  get open() {
    return this.screen !== null;
  }

  setStatus(text) {
    this.statusText = text || '';
    if (this.status) this.status.textContent = this.statusText;
  }

  hide() {
    this._stopCapture();
    this.screen = null;
    this.menu.classList.remove('iv-open');
    this.panel.replaceChildren();
  }

  /** Esc inside menus: back from a sub-screen. Returns true if handled. */
  back() {
    if (this.capturing) {
      this._stopCapture();
      this.show('settings');
      return true;
    }
    if (SUB_SCREENS.has(this.screen) && this.parent) {
      this.show(this.parent);
      return true;
    }
    if (this.screen === 'loadout') {
      this.show('title');
      return true;
    }
    if (this.screen === 'armory') {
      this.show('paused');
      return true;
    }
    return false;
  }

  show(screen, data = null) {
    this._stopCapture();
    if (SUB_SCREENS.has(screen)) {
      if (this.screen && !SUB_SCREENS.has(this.screen)) this.parent = this.screen;
    }
    if (data && screen === 'results') this.results = data;
    if (screen === 'armory') this.armoryData = data || (this.o.actions.armoryState ? this.o.actions.armoryState() : null);
    this.screen = screen;
    this.menu.classList.add('iv-open');
    this.menu.dataset.screen = screen;
    this.status = null;
    const build = {
      loading: () => this._loading(),
      title: () => this._title(),
      loadout: () => this._loadout(),
      paused: () => this._paused(),
      settings: () => this._settings(),
      controls: () => this._controls(),
      results: () => this._results(),
      quit: () => this._quit(),
      credits: () => this._credits(),
      armory: () => this._armory(),
    }[screen];
    this.panel.replaceChildren(...build());
    this.panel.scrollTop = 0;
    if (this.o.onScreen) this.o.onScreen(screen);
  }

  _statusEl() {
    this.status = el('p', 'iv-status', this.statusText);
    return this.status;
  }

  _act(name, ...args) {
    const a = this.o.actions;
    if (a[name]) a[name](...args);
  }

  _loading() {
    return [el('h1', 'iv-title', 'IRON VALLEY'), el('p', 'iv-subtitle', 'Načítání…')];
  }

  _title() {
    // Layout follows the user's mockup (Docs/navrhy/06_uvodni_menu_navrh.webp): logo, accent bar, five items,
    // place name bottom right. Labels stay in sentence case in the DOM; CSS sets them in capitals.
    const logo = el('h1', 'iv-logo');
    logo.setAttribute('aria-label', 'Iron Valley');
    logo.append(logoSvg());
    const nav = el('nav', 'iv-title-nav');
    nav.setAttribute('aria-label', 'Hlavní nabídka');
    nav.append(
      button('Hrát', 'iv-btn-primary iv-title-item', () => this._act('start'), 'start'),
      button('Výcvik', 'iv-title-item', () => this._act('practice'), 'practice'),
      button('Nastavení', 'iv-title-item', () => this.show('settings'), 'settings'),
      button('Autoři', 'iv-title-item', () => this.show('credits'), 'credits'),
      button('Ukončit', 'iv-title-item', () => this._act('quit'), 'quit'),
    );
    nav.addEventListener('keydown', (e) => this._navKeys(e, nav));
    const levels = this.o.levels();
    const current = this.o.currentLevel();
    const row = el('div', 'iv-map-row iv-title-maps');
    row.append(el('span', 'iv-map-label', 'Mapa'));
    for (const l of levels) {
      const b = button(l.name, `iv-btn-small iv-map${l.id === current ? ' iv-selected' : ''}`, () => this._act('selectLevel', l.id), `map-${l.id}`);
      b.disabled = !l.hasMatch;
      if (!l.hasMatch) b.title = 'Mapa nemá zápasová data';
      else if (l.tag) b.title = `${l.name} — ${l.tag}`;
      row.append(b);
    }
    const links = el('div', 'iv-title-links');
    links.append(button('Ovládání', 'iv-link', () => this.show('controls'), 'controls'));
    const hero = el('div', 'iv-hero');
    hero.append(
      logo,
      el('div', 'iv-logo-bar'),
      nav,
      row,
      links,
      this._statusEl(),
      el('p', 'iv-title-foot', 'Prohlížečová verze (three.js, WebGL2), ne verze v Unreal Engine. Postavy a pistole jsou zatím provizorní.'),
    );
    // caption of the picture (it shows Kalné Hamry), not the selected map
    const place = el('p', 'iv-title-place', 'Kalné Hamry');
    place.setAttribute('aria-hidden', 'true');
    requestAnimationFrame(() => {
      const first = nav.querySelector('button');
      if (first && this.screen === 'title' && !document.activeElement?.closest?.('.iv-title-nav')) first.focus({ preventScroll: true });
    });
    return [hero, place];
  }

  /** Arrow keys / Home / End move focus between the title items; Enter and Space use the native button. */
  _navKeys(e, nav) {
    const items = [...nav.querySelectorAll('button:not([disabled])')];
    const i = items.indexOf(document.activeElement);
    let next = -1;
    if (e.key === 'ArrowDown') next = (i + 1) % items.length;
    else if (e.key === 'ArrowUp') next = (i - 1 + items.length) % items.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    if (next >= 0) {
      e.preventDefault();
      items[next].focus();
    }
  }

  _credits() {
    const out = [el('h1', 'iv-title iv-title-small', 'Autoři')];
    const section = (title, lines) => {
      const s = el('section', 'iv-goal iv-credits');
      s.append(el('h2', '', title), ...lines.map((t) => el('p', 'iv-hint', t)));
      return s;
    };
    out.push(
      section('Hra', [
        'IRON VALLEY — prototyp realistické vojenské FPS pro tři týmy.',
        'Zadání, výtvarný směr, úvodní obrázek a reference Kalných Hamrů: autor projektu.',
        'Kód, modely, mapa, zvukový mix a testy: Claude (Anthropic) podle zadání autora projektu.',
      ]),
      section('Knihovny', [
        'three.js, three-mesh-bvh, cannon-es, three-pathfinding (MIT). Navigace se peče nástrojem recast-navigation (MIT) jen při sestavení hry.',
      ]),
      section('Data a písma', [
        'Základní model těla a kostra: MakeHuman / MPFB2 (CC0 1.0), převzato z balíčku anny (NAVER, Apache-2.0).',
        'Písmo Barlow Condensed (The Barlow Project Authors): SIL Open Font License 1.1.',
      ]),
      // CC BY attribution (CC0 authors credited too) — src/data/audio.json, Shared/audio/SOURCES.md
      section('Zvuky — autoři a licence', audioConfig.credits || []),
    );
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Zpět', '', () => this.show(this.parent || 'title'), 'back'));
    out.push(btns);
    return out;
  }

  _loadout() {
    const wd = this.o.weaponsData;
    const rifle = wd[wd.loadout.primary];
    const pistol = wd[wd.loadout.secondary];
    const info = this.o.rulesInfo();
    const team = this.o.teamsData.teams[this.o.teamsData.playerTeam] || {};
    const out = [el('h1', 'iv-title iv-title-small', 'Výbava')];
    const teamLine = el('p', 'iv-subtitle');
    const tn = el('b', 'iv-team-tag', info.playerTeamName);
    tn.style.color = team.color;
    teamLine.append('Hraješ za tým ', tn, ` · ${info.levelName}`);
    out.push(teamLine);
    const grid = el('div', 'iv-loadout');
    // primary
    const prim = el('section', 'iv-slot');
    prim.append(el('h2', '', 'Hlavní zbraň'), el('div', 'iv-slot-weapon', rifle.displayName), el('div', 'iv-slot-ammo', `${info.rifleAmmo}`));
    prim.append(...this._opticRows(this.optic, this.spare, (optic, spare) => {
      this.optic = optic;
      this.spare = spare;
      this.show('loadout');
    }));
    // secondary
    const sec = el('section', 'iv-slot');
    sec.append(el('h2', '', 'Vedlejší zbraň'), el('div', 'iv-slot-weapon', pistol.displayName), el('div', 'iv-slot-ammo', `${info.pistolAmmo}`), el('div', 'iv-slot-note', 'provizorní model · klávesa 2'));
    grid.append(prim, sec);
    out.push(grid);
    out.push(el('p', 'iv-hint', `Aktivní oblast se vybere ze tří míst při startu kola. Cíl: ${info.scoreTarget} bodů nebo nejvíc bodů po ${Math.round(info.timeLimitS / 60)} minutách.`));
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Do boje', 'iv-btn-primary', () => this._act('deploy', { optic: this.optic, spare: this.spare }), 'deploy'), button('Zpět', '', () => this.show('title'), 'back'));
    out.push(btns, this._statusEl());
    return out;
  }

  /**
   * Optic on the rifle + spare optic in the backpack (loadout screen and armory crate). Choosing the spare's optic
   * as the primary swaps the two; the spare can never equal the primary.
   */
  _opticRows(optic, spare, onChange) {
    const rows = [];
    const optRow = el('div', 'iv-optics');
    optRow.append(el('span', 'iv-optics-label', 'Optika:'));
    for (const c of opticChoices()) {
      const b = button(c.name, `iv-btn-small iv-optic${c.id === optic ? ' iv-selected' : ''}`, () => {
        let sp = spare;
        if (c.id === spare) sp = optic !== IRONS ? optic : null;
        onChange(c.id, sp);
      }, `optic-${c.id}`);
      b.title = c.hint || '';
      b.setAttribute('aria-pressed', c.id === optic ? 'true' : 'false');
      optRow.append(b);
    }
    const spareRow = el('div', 'iv-optics iv-spare');
    spareRow.append(el('span', 'iv-optics-label', 'Batoh:'));
    const spareChoices = [{ id: null, name: ATTACHMENTS.noSpare.name }, ...opticChoices().filter((c) => c.id !== IRONS && c.id !== optic)];
    for (const c of spareChoices) {
      const sel = (c.id ?? null) === (spare ?? null);
      const b = button(c.name, `iv-btn-small iv-optic${sel ? ' iv-selected' : ''}`, () => onChange(optic, c.id), `spare-${c.id || 'none'}`);
      b.setAttribute('aria-pressed', sel ? 'true' : 'false');
      spareRow.append(b);
    }
    rows.push(optRow, spareRow);
    const acts = this.o.bindingsStore.get().actions;
    const k = (a, d) => (acts[a] && acts[a][0] ? keyLabel(acts[a][0]) : d);
    const secs = String(ATTACHMENTS.swap.durationS).replace('.', ',');
    rows.push(el('p', 'iv-hint iv-optic-hint', `Náhradní optiku z batohu nasadíš v poli klávesou ${k('swapOptic', 'B')} (${secs} s, mezitím nestřílíš ani nemíříš; znovu ${k('swapOptic', 'B')}, sprint nebo výměna zbraně ji přeruší). U zbrojní bedny na spawnu svého týmu (${k('interact', 'E')}) změníš obě.`));
    return rows;
  }

  _armory() {
    const d = this.armoryData || { mounted: this.optic, spare: this.spare, kit: { optic: this.optic, spare: this.spare } };
    const out = [el('h1', 'iv-title iv-title-small', 'Zbrojní bedna')];
    out.push(el('p', 'iv-subtitle', `Na pušce: ${opticName(d.mounted)} · v batohu: ${opticName(d.spare).toLowerCase()}`));
    const box = el('section', 'iv-slot');
    box.append(el('h2', '', 'Optika IV-7 a náhradní optika'));
    box.append(...this._opticRows(d.kit.optic, d.kit.spare, (optic, spare) => {
      const r = this.o.actions.armoryChoose ? this.o.actions.armoryChoose({ optic, spare }) : { ok: false };
      if (!r.ok) this.setStatus('Změna není možná (jsi u bedny svého týmu?)');
      this.show('armory');
    }));
    out.push(box);
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Zpět do boje', 'iv-btn-primary', () => this._act('resume'), 'resume'));
    out.push(btns, this._statusEl());
    return out;
  }

  _paused() {
    const out = [el('h1', 'iv-title', 'Pauza')];
    const btns = el('div', 'iv-menu-buttons');
    btns.append(
      button('Pokračovat', 'iv-btn-primary', () => this._act('resume'), 'resume'),
      button('Nastavení', '', () => this.show('settings'), 'settings'),
      button('Ovládání', '', () => this.show('controls'), 'controls'),
      button('Opustit kolo', '', () => this._act('leave'), 'leave'),
    );
    out.push(btns, this._statusEl());
    return out;
  }

  _settings() {
    const s = this.o.settings;
    const out = [el('h1', 'iv-title iv-title-small', 'Nastavení')];
    const box = el('section', 'iv-settings');
    const row = (label, input, valueEl) => {
      const r = el('label', 'iv-row');
      r.append(el('span', 'iv-row-label', label), input);
      if (valueEl) r.append(valueEl);
      box.append(r);
    };
    const slider = (key, min, max, step, fmt, label) => {
      const input = el('input');
      input.type = 'range';
      input.min = String(min);
      input.max = String(max);
      input.step = String(step);
      input.value = String(s.get(key));
      input.dataset.setting = key;
      const val = el('span', 'iv-row-value', fmt(s.get(key)));
      input.addEventListener('input', () => {
        const v = s.set(key, Number(input.value));
        val.textContent = fmt(v);
      });
      row(label, input, val);
      return input;
    };
    const check = (key, label) => {
      const input = el('input');
      input.type = 'checkbox';
      input.checked = !!s.get(key);
      input.dataset.setting = key;
      input.addEventListener('change', () => s.set(key, input.checked));
      row(label, input);
      return input;
    };
    const L = s.limits;
    slider('mouseSensitivity', 0.1, 5, 0.05, (v) => v.toFixed(2), 'Citlivost myši');
    slider('fovDeg', L.fovMinDeg, L.fovMaxDeg, 1, (v) => `${Math.round(v)}°`, 'Zorné pole');
    slider('cameraMotion', 0, 1, 0.05, (v) => `${Math.round(v * 100)} %`, 'Pohyb kamery');
    slider('masterVolume', 0, 1, 0.05, (v) => `${Math.round(v * 100)} %`, 'Hlasitost');
    check('adaptiveResolution', 'Automatické rozlišení');
    slider('renderScale', L.renderScaleMin, L.renderScaleMax, 0.05, (v) => `${Math.round(v * 100)} %`, 'Rozlišení obrazu');
    check('showFps', 'Zobrazit FPS');
    const reset = button('Obnovit výchozí', 'iv-btn-small', () => {
      s.reset();
      this.show('settings');
    }, 'reset-settings');
    box.append(reset);

    const keys = el('section', 'iv-keybinds');
    keys.append(el('h2', '', 'Klávesy'));
    const labels = this.o.bindingsStore.get().labels || {};
    const actions = this.o.bindingsStore.get().actions;
    const list = el('div', 'iv-bind-list');
    for (const a of REBINDABLE) {
      const r = el('div', 'iv-bind-row');
      r.append(el('span', 'iv-bind-label', labels[a] || a));
      const codes = actions[a] || [];
      const txt = this.capturing === a ? 'Stiskni klávesu… (Esc zruší)' : codes.length ? codes.map(keyLabel).join(' / ') : '— nepřiřazeno —';
      const b = button(txt, `iv-btn-small iv-bind${this.capturing === a ? ' iv-capturing' : ''}`, () => this._startCapture(a), `bind-${a}`);
      r.append(b);
      list.append(r);
    }
    keys.append(list);
    keys.append(el('p', 'iv-hint', 'Klikni na akci a stiskni novou klávesu nebo tlačítko myši. Esc (menu) změnit nelze.'));
    keys.append(button('Výchozí klávesy', 'iv-btn-small', () => {
      this.o.bindingsStore.reset();
      this.show('settings');
    }, 'reset-keys'));
    const cols = el('div', 'iv-cols');
    cols.append(box, keys);
    out.push(cols);
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Zpět', '', () => this.show(this.parent || 'title'), 'back'));
    out.push(btns);
    return out;
  }

  _startCapture(action) {
    this._stopCapture();
    this.capturing = action;
    // capture phase on window: runs before the game's input listener, which never sees this key
    window.addEventListener('keydown', this._onCaptureKey, true);
    setTimeout(() => {
      if (this.capturing === action) window.addEventListener('mousedown', this._onCaptureMouse, true);
    }, 0);
    this.panel.querySelectorAll('.iv-bind').forEach((b) => {
      if (b.dataset.action === `bind-${action}`) {
        b.textContent = 'Stiskni klávesu… (Esc zruší)';
        b.classList.add('iv-capturing');
      }
    });
  }

  _stopCapture() {
    window.removeEventListener('keydown', this._onCaptureKey, true);
    window.removeEventListener('mousedown', this._onCaptureMouse, true);
    this.capturing = null;
  }

  _captureKey(e) {
    if (!this.capturing) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const action = this.capturing;
    this._stopCapture();
    if (e.code !== 'Escape') {
      const ok = this.o.bindingsStore.bind(action, e.code);
      if (!ok) this.setStatus(`Klávesu ${keyLabel(e.code)} nelze přiřadit.`);
      else this.setStatus('');
    }
    this.show('settings');
  }

  _captureMouse(e) {
    if (!this.capturing) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const action = this.capturing;
    this._stopCapture();
    this.o.bindingsStore.bind(action, `Mouse${e.button}`);
    this.show('settings');
  }

  _controls() {
    const out = [el('h1', 'iv-title iv-title-small', 'Ovládání')];
    const b = this.o.bindingsStore.get();
    const list = el('dl', 'iv-keys');
    list.append(el('dt', '', 'Rozhlížení'), el('dd', '', 'Myš'));
    const pretty = (codes) => (codes.length ? codes.filter((c) => !c.startsWith('Numpad')).map(keyLabel).join(' / ') : '—');
    for (const a of CONTROL_ROWS) {
      const codes = b.actions[a];
      if (!codes) continue;
      list.append(el('dt', '', (b.labels && b.labels[a]) || a), el('dd', '', pretty(codes)));
    }
    const goal = el('section', 'iv-goal');
    const info = this.o.rulesInfo();
    goal.append(
      el('h2', '', 'Cíl hry'),
      el('p', '', `Tři týmy po šesti bojují o jednu aktivní oblast (${info.zoneNames}). Oblast drží tým, který v ní má víc živých vojáků než každý jiný tým.`),
      el('p', '', `Držení dává ${info.pointsPerAward} bod každé ${info.pointInterval} s. Vyhrává tým, který první získá ${info.scoreTarget} bodů, nebo má nejvíc bodů po ${Math.round(info.timeLimitS / 60)} minutách. Shoda je remíza.`),
      el('p', '', `Po smrti se vrátíš za ${info.respawnDelay} s na bezpečné místo u svého týmu. Spojence poznáš podle modré barvy a jmenovky; střelba do spojenců nezraňuje.`),
      el('p', 'iv-hint', 'Dřep doporučujeme klávesou C — Ctrl+W v prohlížeči zavírá kartu.'),
    );
    const cols = el('div', 'iv-cols');
    const keys = el('section', 'iv-controls');
    keys.append(el('h2', '', 'Klávesy'), list);
    cols.append(keys, goal);
    out.push(cols);
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Zpět', '', () => this.show(this.parent || 'title'), 'back'));
    out.push(btns);
    return out;
  }

  _results() {
    const r = this.results || {};
    const out = [el('h1', 'iv-title iv-title-small', 'Výsledek kola')];
    const head = el('div', 'iv-result-head');
    if (r.draw) head.append(el('span', 'iv-result-winner', 'Remíza'));
    else {
      const w = el('span', 'iv-result-winner', `Vítězí tým ${r.winnerName}`);
      w.style.color = r.winnerColor;
      head.append(w);
    }
    head.append(el('span', 'iv-result-reason', r.reason === 'score_target' ? `dosažením ${r.scoreTarget} bodů` : 'vypršel čas kola'));
    out.push(head);
    const table = el('table', 'iv-result-table');
    const hr = el('tr');
    hr.append(el('th', '', 'Tým'), el('th', '', 'Body'), el('th', '', 'Zabití'));
    table.append(hr);
    for (const t of r.teams || []) {
      const tr = el('tr', t.own ? 'iv-own' : '');
      const name = el('td', 'iv-result-team', t.name + (t.own ? ' (ty)' : ''));
      name.style.color = t.color;
      tr.append(name, el('td', '', String(t.score)), el('td', '', String(t.kills)));
      table.append(tr);
    }
    out.push(table);
    if (r.player) out.push(el('p', 'iv-subtitle', `Tvoje zabití: ${r.player.kills} · smrti: ${r.player.deaths}`));
    const btns = el('div', 'iv-menu-buttons');
    btns.append(
      button('Nové kolo', 'iv-btn-primary', () => this._act('newRound'), 'new-round'),
      button('Změnit výbavu', '', () => this._act('changeLoadout'), 'change-loadout'),
      button('Hlavní menu', '', () => this._act('mainMenu'), 'main-menu'),
    );
    out.push(btns, this._statusEl());
    return out;
  }

  _quit() {
    const out = [el('h1', 'iv-title iv-title-small', 'Ukončit hru')];
    out.push(el('p', 'iv-subtitle', 'Hru ukončíš zavřením karty prohlížeče. Kurzor myši je uvolněný.'));
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Zpět', '', () => this.show(this.parent || 'title'), 'back'));
    out.push(btns);
    return out;
  }
}
