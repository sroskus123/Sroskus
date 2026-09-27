// HUD and menus (DOM overlay, Czech texts). Shows only real game state.

import { keyLabel } from '../player/input.js';

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

export class Hud {
  /**
   * @param {HTMLElement} root
   * @param {object} o { bindings, settings, events, levelName, onStart, onResume }
   */
  constructor(root, { bindings, settings, events, levelName, onStart, onResume }) {
    this.root = root;
    this.settings = settings;
    this.events = events;
    this.bindings = bindings;

    // --- in-game HUD ---
    this.hud = el('div', 'iv-hud');
    this.hud.setAttribute('aria-hidden', 'true');
    this.location = el('div', 'iv-location');
    this.location.append(el('span', 'iv-location-name', levelName), el('span', 'iv-location-tag', 'vývojová mapa'));
    this.crosshair = el('div', 'iv-crosshair');
    for (const c of ['t', 'b', 'l', 'r', 'dot']) this.crosshair.append(el('i', `iv-ch-${c}`));
    this.hitmarker = el('div', 'iv-hitmarker');
    this.ammoBox = el('div', 'iv-ammo');
    this.weaponName = el('div', 'iv-weapon-name', '');
    this.ammoMag = el('span', 'iv-ammo-mag', '30');
    this.ammoReserve = el('span', 'iv-ammo-res', '/ 120');
    const ammoLine = el('div', 'iv-ammo-line');
    ammoLine.append(this.ammoMag, this.ammoReserve);
    this.reloadBar = el('div', 'iv-reload');
    this.reloadFill = el('i');
    this.reloadBar.append(this.reloadFill);
    this.ammoBox.append(this.weaponName, ammoLine, this.reloadBar);
    this.stance = el('div', 'iv-stance', '');
    this.notice = el('div', 'iv-notice', '');
    this.fps = el('div', 'iv-fps', '');
    this.placeholderNote = el('div', 'iv-placeholder-note', '');
    this.hud.append(this.location, this.crosshair, this.hitmarker, this.ammoBox, this.stance, this.notice, this.fps, this.placeholderNote);

    // --- menu (start + pause) ---
    this.menu = el('div', 'iv-menu');
    this.menu.setAttribute('role', 'dialog');
    this.menu.setAttribute('aria-modal', 'true');
    const panel = el('div', 'iv-panel');
    this.title = el('h1', 'iv-title', 'IRON VALLEY');
    this.subtitle = el('p', 'iv-subtitle', `${levelName} · prohlížečová verze`);
    this.startBtn = el('button', 'iv-btn iv-btn-primary', 'Hrát');
    this.startBtn.type = 'button';
    this.startBtn.addEventListener('click', () => (this.mode === 'start' ? onStart() : onResume()));
    this.status = el('p', 'iv-status', '');
    const cols = el('div', 'iv-cols');
    cols.append(this._buildControls(), this._buildSettings());
    const foot = el(
      'p',
      'iv-foot',
      'Tato verze běží v prohlížeči (three.js, WebGL2) a slouží k testování pohybu a střelby. Nejde o verzi v Unreal Engine.',
    );
    panel.append(this.title, this.subtitle, this.startBtn, this.status, cols, foot);
    this.menu.append(panel);

    // --- touch / narrow note ---
    this.touchNote = el('div', 'iv-touch-note');
    this.touchNote.append(
      el('strong', '', 'Hra vyžaduje klávesnici a myš.'),
      el('span', '', ' Na dotykovém nebo příliš úzkém displeji ji nelze ovládat. Otevři ji na počítači (šířka okna alespoň 960 px).'),
    );

    root.append(this.hud, this.menu, this.touchNote);
    this.mode = 'start';
    this.noticeTimer = 0;
    this.hitTimer = 0;
    this._updateTouchNote();
    window.addEventListener('resize', () => this._updateTouchNote());
    this.setMode('start');
  }

  _buildControls() {
    const box = el('section', 'iv-controls');
    box.append(el('h2', '', 'Ovládání'));
    const list = el('dl', 'iv-keys');
    const labels = this.bindings.labels || {};
    const show = ['moveForward', 'moveBackward', 'moveLeft', 'moveRight', 'fire', 'aim', 'reload', 'sprint', 'walk', 'crouch', 'jump', 'interact', 'weapon1', 'weapon2', 'menu'];
    const pretty = (codes) => codes.filter((c) => !c.startsWith('Arrow') && !c.startsWith('Numpad')).map(keyLabel).join(' / ');
    list.append(el('dt', '', 'Rozhlížení'), el('dd', '', 'Myš'));
    for (const a of show) {
      const codes = this.bindings.actions[a];
      if (!codes) continue;
      list.append(el('dt', '', labels[a] || a), el('dd', '', pretty(codes)));
    }
    box.append(list);
    box.append(el('p', 'iv-hint', 'Dřep doporučujeme klávesou C — Ctrl+W v prohlížeči zavírá kartu.'));
    return box;
  }

  _buildSettings() {
    const s = this.settings;
    const box = el('section', 'iv-settings');
    box.append(el('h2', '', 'Nastavení'));
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
    this.inputs = {
      mouseSensitivity: slider('mouseSensitivity', 0.1, 5, 0.05, (v) => v.toFixed(2), 'Citlivost myši'),
      fovDeg: slider('fovDeg', L.fovMinDeg, L.fovMaxDeg, 1, (v) => `${Math.round(v)}°`, 'Zorné pole (horiz.)'),
      cameraMotion: slider('cameraMotion', 0, 1, 0.05, (v) => `${Math.round(v * 100)} %`, 'Pohyb kamery'),
      adaptiveResolution: check('adaptiveResolution', 'Automatické rozlišení'),
      renderScale: slider('renderScale', L.renderScaleMin, L.renderScaleMax, 0.05, (v) => `${Math.round(v * 100)} %`, 'Rozlišení vykreslování'),
      showFps: check('showFps', 'Zobrazit FPS'),
    };
    const reset = el('button', 'iv-btn iv-btn-small', 'Obnovit výchozí');
    reset.type = 'button';
    reset.addEventListener('click', () => {
      s.reset();
      for (const [k, input] of Object.entries(this.inputs)) {
        if (input.type === 'checkbox') input.checked = !!s.get(k);
        else {
          input.value = String(s.get(k));
          input.dispatchEvent(new Event('input'));
        }
      }
    });
    box.append(reset);
    return box;
  }

  _updateTouchNote() {
    const narrow = window.innerWidth < 900;
    let touchOnly = false;
    try {
      touchOnly = window.matchMedia('(pointer: coarse)').matches && !window.matchMedia('(any-pointer: fine)').matches;
    } catch {
      touchOnly = false;
    }
    this.touchNote.classList.toggle('iv-show', narrow || touchOnly);
  }

  setMode(mode) {
    this.mode = mode;
    this.menu.classList.toggle('iv-open', mode === 'start' || mode === 'paused' || mode === 'loading');
    this.hud.classList.toggle('iv-open', mode === 'playing' || mode === 'paused');
    if (mode === 'start') {
      this.title.textContent = 'IRON VALLEY';
      this.startBtn.textContent = 'Hrát';
      this.startBtn.disabled = false;
    } else if (mode === 'paused') {
      this.title.textContent = 'Pauza';
      this.startBtn.textContent = 'Pokračovat';
      this.startBtn.disabled = false;
    } else if (mode === 'loading') {
      this.title.textContent = 'IRON VALLEY';
      this.startBtn.textContent = 'Načítání…';
      this.startBtn.disabled = true;
    }
  }

  setStatus(text) {
    this.status.textContent = text || '';
  }

  showNotice(text, seconds = 2.5) {
    this.notice.textContent = text;
    this.notice.classList.add('iv-show');
    this.noticeTimer = seconds;
  }

  showHitmarker(kill = false) {
    this.hitmarker.classList.add('iv-show');
    this.hitmarker.classList.toggle('iv-kill', kill);
    this.hitTimer = 0.12;
  }

  setPlaceholderNote(text) {
    this.placeholderNote.textContent = text || '';
  }

  /** Timers advance with game time (fixed tick), so they pause with the game. */
  tick(dt) {
    if (this.noticeTimer > 0) {
      this.noticeTimer -= dt;
      if (this.noticeTimer <= 0) this.notice.classList.remove('iv-show');
    }
    if (this.hitTimer > 0) {
      this.hitTimer -= dt;
      if (this.hitTimer <= 0) this.hitmarker.classList.remove('iv-show');
    }
  }

  /** Per-frame refresh from real state. */
  update(dt, { weapon, player, fps, showFps, sprinting }) {
    if (weapon) {
      const w = weapon;
      const mag = String(w.magazine);
      if (this.ammoMag.textContent !== mag) this.ammoMag.textContent = mag;
      const res = `/ ${w.reserve}`;
      if (this.ammoReserve.textContent !== res) this.ammoReserve.textContent = res;
      this.ammoMag.classList.toggle('iv-low', w.magazine <= 5);
      this.reloadBar.classList.toggle('iv-show', w.state === 'reloading');
      this.reloadFill.style.transform = `scaleX(${w.reloadProgress.toFixed(3)})`;
      this.crosshair.style.opacity = String(Math.max(0, 1 - w.ads * 2.2) * (sprinting ? 0.35 : 1));
    }
    if (player) {
      const txt = player.crouched ? 'DŘEP' : sprinting ? 'SPRINT' : '';
      if (this.stance.textContent !== txt) this.stance.textContent = txt;
    }
    this.fps.style.display = showFps ? 'block' : 'none';
    if (showFps) this.fps.textContent = `${fps.toFixed(0)} FPS`;
  }
}
