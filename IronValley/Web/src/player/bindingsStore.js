// Key rebinding: user overrides of src/data/input_bindings.json, persisted in localStorage (best
// effort: storage may be missing or throw in sandboxed frames, then bindings last for the session).
// Only actions listed as rebindable can change; Esc (menu) stays fixed so the cursor can always be freed.

const STORAGE_KEY = 'ironvalley.bindings.v1';

export const REBINDABLE = [
  'moveForward',
  'moveBackward',
  'moveLeft',
  'moveRight',
  'fire',
  'aim',
  'reload',
  'sprint',
  'walk',
  'crouch',
  'jump',
  'interact',
  'swapOptic',
  'weapon1',
  'weapon2',
];

const CODE_RE = /^(Key[A-Z]|Digit[0-9]|Numpad[0-9]|Mouse[0-4]|F([1-9]|1[0-2])|Arrow(Up|Down|Left|Right)|Shift(Left|Right)|Control(Left|Right)|Alt(Left|Right)|Space|Tab|CapsLock|Backquote|Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Enter|Backspace|Insert|Delete|Home|End|PageUp|PageDown)$/;

/** Can this code be bound (Escape and unknown codes cannot)? */
export function isBindableCode(code) {
  return typeof code === 'string' && code !== 'Escape' && CODE_RE.test(code);
}

function clone(o) {
  return JSON.parse(JSON.stringify(o));
}

export class BindingsStore {
  /**
   * @param {object} defaults  parsed input_bindings.json
   * @param {Storage|null} storage
   */
  constructor(defaults, storage = null) {
    this.defaults = defaults;
    this.storage = storage;
    this.overrides = this._load();
    this.current = this._merge();
    this._listeners = new Set();
  }

  _load() {
    if (!this.storage) return {};
    try {
      const txt = this.storage.getItem(STORAGE_KEY);
      if (!txt) return {};
      const raw = JSON.parse(txt);
      const out = {};
      for (const a of REBINDABLE) {
        const v = raw && raw[a];
        if (Array.isArray(v) && v.every(isBindableCode)) out[a] = v.slice(0, 3);
      }
      return out;
    } catch {
      return {};
    }
  }

  _save() {
    if (!this.storage) return;
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(this.overrides));
    } catch {
      /* storage unavailable: bindings stay for this session only */
    }
  }

  _merge() {
    const b = clone(this.defaults);
    for (const [a, codes] of Object.entries(this.overrides)) b.actions[a] = codes.slice();
    return b;
  }

  get() {
    return this.current;
  }

  onChange(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  _emit() {
    for (const fn of this._listeners) fn(this.current);
  }

  /**
   * Binds `code` as the only key of `action`. The code is removed from every other action that had it
   * (no double bindings); an action that loses its last key stays unbound until the player rebinds it.
   * Returns true on success.
   */
  bind(action, code) {
    if (!REBINDABLE.includes(action) || !isBindableCode(code)) return false;
    const entries = Object.entries(this.current.actions);
    // fixed actions (menu, F3) keep their keys
    if (entries.some(([a, list]) => a !== action && !REBINDABLE.includes(a) && Array.isArray(list) && list.includes(code))) return false;
    for (const [a, list] of entries) {
      if (a === action || !Array.isArray(list) || !list.includes(code)) continue;
      this.overrides[a] = list.filter((c) => c !== code);
    }
    this.overrides[action] = [code];
    this.current = this._merge();
    this._save();
    this._emit();
    return true;
  }

  reset() {
    this.overrides = {};
    this.current = this._merge();
    this._save();
    this._emit();
  }
}
