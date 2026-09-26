// Player settings (sensitivity, FOV, camera motion, render scale, master volume) with validation and
// best-effort persistence in localStorage (which may be unavailable in sandboxed frames).

import defaults from '../data/settings_defaults.json' with { type: 'json' };

const STORAGE_KEY = 'ironvalley.settings.v1';

function clampNum(v, lo, hi, fallback) {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

export function sanitizeSettings(raw) {
  const d = defaults;
  const s = raw || {};
  return {
    mouseSensitivity: clampNum(s.mouseSensitivity, 0.1, 5, d.mouseSensitivity),
    fovDeg: Math.round(clampNum(s.fovDeg, d.fovMinDeg, d.fovMaxDeg, d.fovDeg)),
    cameraMotion: clampNum(s.cameraMotion, 0, 1, d.cameraMotion),
    adaptiveResolution: typeof s.adaptiveResolution === 'boolean' ? s.adaptiveResolution : d.adaptiveResolution,
    renderScale: clampNum(s.renderScale, d.renderScaleMin, d.renderScaleMax, d.renderScale),
    showFps: typeof s.showFps === 'boolean' ? s.showFps : d.showFps,
    masterVolume: clampNum(s.masterVolume, 0, 1, d.masterVolume),
  };
}

export class Settings {
  constructor({ storage = null } = {}) {
    this.storage = storage;
    this.values = sanitizeSettings(this._load());
    this._listeners = new Set();
    this.limits = {
      fovMinDeg: defaults.fovMinDeg,
      fovMaxDeg: defaults.fovMaxDeg,
      renderScaleMin: defaults.renderScaleMin,
      renderScaleMax: defaults.renderScaleMax,
    };
  }

  _load() {
    if (!this.storage) return defaults;
    try {
      const txt = this.storage.getItem(STORAGE_KEY);
      return txt ? { ...defaults, ...JSON.parse(txt) } : defaults;
    } catch {
      return defaults;
    }
  }

  save() {
    if (!this.storage) return;
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(this.values));
    } catch {
      /* storage unavailable: settings stay for this session only */
    }
  }

  get(key) {
    return this.values[key];
  }

  set(key, value) {
    const next = sanitizeSettings({ ...this.values, [key]: value });
    if (next[key] === this.values[key]) return this.values[key];
    this.values = next;
    this.save();
    for (const fn of this._listeners) fn(key, next[key], next);
    return next[key];
  }

  onChange(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  reset() {
    this.values = sanitizeSettings(defaults);
    this.save();
    for (const fn of this._listeners) fn('*', null, this.values);
  }
}
