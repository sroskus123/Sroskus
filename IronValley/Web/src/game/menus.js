// Menus (DOM, Czech): title, loadout, pause, settings (incl. key rebinding and master volume), controls,
// results and quit. Only the active screen is in the DOM, so there is exactly one primary button
// (.iv-btn-primary) at a time. While a menu is open the game input is disabled and the cursor is free.

import { keyLabel } from '../player/input.js';
import { REBINDABLE } from '../player/bindingsStore.js';
import audioConfig from '../data/audio.json' with { type: 'json' };

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

const CONTROL_ROWS = ['moveForward', 'moveBackward', 'moveLeft', 'moveRight', 'fire', 'aim', 'reload', 'sprint', 'walk', 'crouch', 'jump', 'interact', 'weapon1', 'weapon2', 'menu'];

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
    this.menu.append(this.panel);
    root.append(this.menu);
    // every click in a menu is a user gesture (audio unlock etc.)
    this.panel.addEventListener('click', () => o.actions.gesture && o.actions.gesture(), true);
    this.screen = null;
    this.parent = null; // screen to return to from settings / controls
    this.statusText = '';
    this.optic = (o.weaponsData.iv7_carbine.optics && o.weaponsData.iv7_carbine.optics.default) || 'collimator';
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
    if ((this.screen === 'settings' || this.screen === 'controls' || this.screen === 'quit') && this.parent) {
      this.show(this.parent);
      return true;
    }
    if (this.screen === 'loadout') {
      this.show('title');
      return true;
    }
    return false;
  }

  show(screen, data = null) {
    this._stopCapture();
    if (screen === 'settings' || screen === 'controls' || screen === 'quit') {
      if (this.screen && this.screen !== 'settings' && this.screen !== 'controls' && this.screen !== 'quit') this.parent = this.screen;
    }
    if (data && screen === 'results') this.results = data;
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
    const out = [el('h1', 'iv-title', 'IRON VALLEY'), el('p', 'iv-subtitle', 'Tři týmy · jedna oblast · 10 minut')];
    const levels = this.o.levels();
    const row = el('div', 'iv-map-row');
    row.append(el('span', 'iv-map-label', 'Mapa'));
    const current = this.o.currentLevel();
    for (const l of levels) {
      const b = button(l.name, `iv-btn-small iv-map${l.id === current ? ' iv-selected' : ''}`, () => this._act('selectLevel', l.id), `map-${l.id}`);
      b.disabled = !l.hasMatch;
      if (!l.hasMatch) b.title = 'Mapa nemá zápasová data';
      row.append(b);
    }
    const btns = el('div', 'iv-menu-buttons');
    btns.append(
      button('Začít', 'iv-btn-primary', () => this._act('start'), 'start'),
      button('Trénink (bez botů)', '', () => this._act('practice'), 'practice'),
      button('Nastavení', '', () => this.show('settings'), 'settings'),
      button('Ovládání', '', () => this.show('controls'), 'controls'),
      button('Ukončit', '', () => this._act('quit'), 'quit'),
    );
    out.push(row, btns, this._statusEl());
    out.push(el('p', 'iv-foot', 'Prohlížečová verze (three.js, WebGL2), ne verze v Unreal Engine. Postavy, pistole a zvuky jsou provizorní.'));
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
    const optRow = el('div', 'iv-optics');
    optRow.append(el('span', 'iv-optics-label', 'Mířidla:'));
    for (const opt of rifle.optics.list) {
      const b = button(opt.name, `iv-btn-small iv-optic${opt.id === this.optic ? ' iv-selected' : ''}`, () => {
        this.optic = opt.id;
        this.show('loadout');
      }, `optic-${opt.id}`);
      b.setAttribute('aria-pressed', opt.id === this.optic ? 'true' : 'false');
      optRow.append(b);
    }
    prim.append(optRow);
    // secondary
    const sec = el('section', 'iv-slot');
    sec.append(el('h2', '', 'Vedlejší zbraň'), el('div', 'iv-slot-weapon', pistol.displayName), el('div', 'iv-slot-ammo', `${info.pistolAmmo}`), el('div', 'iv-slot-note', 'provizorní model · klávesa 2'));
    grid.append(prim, sec);
    out.push(grid);
    out.push(el('p', 'iv-hint', `Aktivní oblast se vybere ze tří míst při startu kola. Cíl: ${info.scoreTarget} bodů nebo nejvíc bodů po ${Math.round(info.timeLimitS / 60)} minutách.`));
    const btns = el('div', 'iv-menu-buttons');
    btns.append(button('Do boje', 'iv-btn-primary', () => this._act('deploy', { optic: this.optic }), 'deploy'), button('Zpět', '', () => this.show('title'), 'back'));
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
    // sound credits (CC BY attribution; CC0 authors credited too) — src/data/audio.json, Shared/audio/SOURCES.md
    const credits = el('section', 'iv-goal iv-credits');
    credits.append(el('h2', '', 'Zvuky — autoři a licence'), ...(audioConfig.credits || []).map((t) => el('p', 'iv-hint', t)));
    out.push(credits);
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
