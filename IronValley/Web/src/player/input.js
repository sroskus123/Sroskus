// Input manager: data-driven bindings (input_bindings.json), pointer lock with a
// click-and-drag fallback, focus-loss safety, and an injection API used by tests.
//
// Keys are identified by KeyboardEvent.code (physical position, layout independent), mouse
// buttons as "Mouse0" (left), "Mouse1" (middle), "Mouse2" (right).
//
// Held state is sampled by the fixed simulation tick. Presses are latched until the next
// tick consumes them, so a tap shorter than one tick is never lost.

export function buildBindingMap(bindings) {
  const codeToActions = new Map();
  for (const [action, codes] of Object.entries(bindings.actions || {})) {
    if (!Array.isArray(codes)) throw new Error(`Binding for ${action} must be an array`);
    for (const code of codes) {
      if (typeof code !== 'string' || !code) throw new Error(`Invalid key code for ${action}`);
      if (!codeToActions.has(code)) codeToActions.set(code, []);
      codeToActions.get(code).push(action);
    }
  }
  return codeToActions;
}

/** Human readable label for a key code (Czech UI). */
export function keyLabel(code) {
  if (code.startsWith('Key')) return code.slice(3);
  if (code.startsWith('Digit')) return code.slice(5);
  if (code.startsWith('Numpad')) return `Num ${code.slice(6)}`;
  const map = {
    Mouse0: 'Levé tlačítko myši',
    Mouse1: 'Prostřední tlačítko',
    Mouse2: 'Pravé tlačítko myši',
    ShiftLeft: 'Shift',
    ShiftRight: 'Pravý Shift',
    ControlLeft: 'Ctrl',
    ControlRight: 'Pravý Ctrl',
    AltLeft: 'Alt',
    Space: 'Mezerník',
    Escape: 'Esc',
    ArrowUp: '↑',
    ArrowDown: '↓',
    ArrowLeft: '←',
    ArrowRight: '→',
  };
  return map[code] || code;
}

export class InputManager {
  /**
   * @param {object} bindings  parsed input_bindings.json
   * @param {import('../engine/events.js').EventBus} events
   */
  constructor(bindings, events) {
    this.bindings = bindings;
    this.events = events;
    this.codeToActions = buildBindingMap(bindings);
    this.heldCodes = new Set();
    this.held = new Map(); // action -> count of held codes
    this.pressed = new Set(); // actions pressed since last consumeTick()
    this.lookDX = 0;
    this.lookDY = 0;
    this.enabled = false; // gameplay input accepted (false in menus)
    this.pointerLocked = false;
    this.lookMode = 'none'; // 'lock' | 'drag' | 'none'
    this.dragging = false;
    this.target = null;
    this.stats = { releasedAll: 0, lockRequests: 0, lockErrors: 0 };
    this._listeners = [];
    this._lockSupported = true;
    this._lastLockTry = -Infinity;
  }

  // ------------------------------------------------------------------ DOM wiring

  attach(target, win = window, doc = document) {
    this.target = target;
    this.win = win;
    this.doc = doc;
    const on = (obj, type, fn, opts) => {
      obj.addEventListener(type, fn, opts);
      this._listeners.push(() => obj.removeEventListener(type, fn, opts));
    };
    on(win, 'keydown', (e) => {
      const handled = this.handleKeyDown(e.code, e.repeat);
      if (handled && this.enabled) e.preventDefault();
    });
    on(win, 'keyup', (e) => {
      const handled = this.handleKeyUp(e.code);
      if (handled && this.enabled) e.preventDefault();
    });
    on(target, 'mousedown', (e) => {
      if (this.enabled && this.lookMode === 'drag') {
        this.dragging = true;
        // A refused lock can be transient (e.g. re-locking right after Esc); a click is a
        // user gesture, so retry now and then. Stays in drag mode if it keeps failing.
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        if (!this.pointerLocked && this._lockSupported && now - this._lastLockTry > 1500) {
          this._lastLockTry = now;
          this.requestPointerLock();
        }
      }
      this.handleMouseButton(e.button, true);
      if (this.enabled) e.preventDefault();
    });
    on(win, 'mouseup', (e) => {
      this.handleMouseButton(e.button, false);
      if (e.buttons === 0) this.dragging = false;
    });
    on(win, 'mousemove', (e) => {
      if (this.lookMode === 'lock' && this.pointerLocked) this.handleMouseMove(e.movementX, e.movementY);
      else if (this.lookMode === 'drag' && this.dragging) this.handleMouseMove(e.movementX, e.movementY);
    });
    on(target, 'contextmenu', (e) => e.preventDefault());
    on(doc, 'pointerlockchange', () => this._onPointerLockChange());
    on(doc, 'pointerlockerror', () => this._onPointerLockError());
    on(win, 'blur', () => this.releaseAll('blur'));
    on(doc, 'visibilitychange', () => {
      if (doc.visibilityState === 'hidden') this.releaseAll('hidden');
    });
  }

  detach() {
    for (const off of this._listeners) off();
    this._listeners = [];
  }

  /** Must be called from a user gesture (click). Falls back to drag-look on failure. */
  requestPointerLock() {
    const el = this.target;
    this.stats.lockRequests++;
    if (!el || typeof el.requestPointerLock !== 'function') {
      this._lockSupported = false;
      this._enterDragMode('unsupported');
      return;
    }
    try {
      const res = el.requestPointerLock({ unadjustedMovement: false });
      if (res && typeof res.then === 'function') {
        res.then(
          () => {},
          (err) => this._onPointerLockError(err),
        );
      }
      // If nothing happens (sandboxed iframe without allow-pointer-lock) fall back quickly.
      clearTimeout(this._lockTimer);
      this._lockTimer = setTimeout(() => {
        if (!this.pointerLocked && this.lookMode !== 'drag') this._enterDragMode('timeout');
      }, 600);
    } catch (err) {
      this._onPointerLockError(err);
    }
  }

  exitPointerLock() {
    if (this.doc && this.doc.pointerLockElement && this.doc.exitPointerLock) this.doc.exitPointerLock();
  }

  _onPointerLockChange() {
    const locked = !!this.doc && this.doc.pointerLockElement === this.target;
    const was = this.pointerLocked;
    this.pointerLocked = locked;
    if (locked) {
      clearTimeout(this._lockTimer);
      this.lookMode = 'lock';
      this.events.emit('input:pointerlock', { locked: true });
    } else if (was) {
      // Browser released the cursor (usually Esc): stop everything and let the game pause.
      this.releaseAll('pointerlock-lost');
      this.events.emit('input:pointerlock', { locked: false });
      this.events.emit('input:menu', { reason: 'pointerlock-lost' });
    }
  }

  _onPointerLockError(err) {
    this.stats.lockErrors++;
    this._enterDragMode(err && err.name ? err.name : 'error');
  }

  _enterDragMode(reason) {
    clearTimeout(this._lockTimer);
    if (this.pointerLocked) return;
    if (this.lookMode !== 'drag') {
      this.lookMode = 'drag';
      this.events.emit('input:fallback', { reason });
    }
  }

  // ------------------------------------------------------------------ core handlers (also used by tests)

  handleKeyDown(code, repeat = false) {
    const actions = this.codeToActions.get(code);
    if (code === 'Escape' || (actions && actions.includes('menu'))) {
      if (!repeat) this.events.emit('input:menu', { reason: 'key' });
      return true;
    }
    if (!actions) return false;
    if (actions.includes('toggleFps') && !repeat) this.events.emit('input:toggleFps', {});
    if (!this.enabled) return true;
    if (this.heldCodes.has(code)) return true; // auto-repeat
    this.heldCodes.add(code);
    for (const a of actions) {
      this.held.set(a, (this.held.get(a) || 0) + 1);
      this.pressed.add(a);
    }
    return true;
  }

  handleKeyUp(code) {
    const actions = this.codeToActions.get(code);
    if (!actions) return false;
    if (!this.heldCodes.has(code)) return true;
    this.heldCodes.delete(code);
    for (const a of actions) {
      const n = (this.held.get(a) || 0) - 1;
      if (n <= 0) this.held.delete(a);
      else this.held.set(a, n);
    }
    return true;
  }

  handleMouseButton(button, down) {
    const code = `Mouse${button}`;
    return down ? this.handleKeyDown(code) : this.handleKeyUp(code);
  }

  handleMouseMove(dx, dy) {
    if (!this.enabled) return;
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    // Guard against the occasional huge spike some browsers emit on lock changes.
    const lim = 400;
    this.lookDX += Math.max(-lim, Math.min(lim, dx));
    this.lookDY += Math.max(-lim, Math.min(lim, dy));
  }

  /** Releases every held key/button (focus loss, menu, pointer lock lost). */
  releaseAll(reason = 'manual') {
    const hadInput = this.heldCodes.size > 0 || this.pressed.size > 0;
    this.heldCodes.clear();
    this.held.clear();
    this.pressed.clear();
    this.lookDX = 0;
    this.lookDY = 0;
    this.dragging = false;
    this.stats.releasedAll++;
    this.events.emit('input:released', { reason, hadInput });
  }

  setEnabled(on) {
    this.enabled = !!on;
    if (!on) this.releaseAll('disabled');
  }

  // ------------------------------------------------------------------ queries

  isHeld(action) {
    return this.held.has(action);
  }

  /** Held now or pressed since the last tick (catches taps shorter than a tick). */
  isActive(action) {
    return this.held.has(action) || this.pressed.has(action);
  }

  wasPressed(action) {
    return this.pressed.has(action);
  }

  axis(positive, negative) {
    return (this.isActive(positive) ? 1 : 0) - (this.isActive(negative) ? 1 : 0);
  }

  /** Called by the simulation after each tick. */
  consumeTick() {
    this.pressed.clear();
  }

  /** Returns and clears accumulated mouse look deltas (pixels). */
  consumeLook() {
    const d = { dx: this.lookDX, dy: this.lookDY };
    this.lookDX = 0;
    this.lookDY = 0;
    return d;
  }

  getState() {
    return {
      enabled: this.enabled,
      pointerLocked: this.pointerLocked,
      lookMode: this.lookMode,
      heldCodes: [...this.heldCodes],
      heldActions: [...this.held.keys()],
      stats: { ...this.stats },
    };
  }
}
