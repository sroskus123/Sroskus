// Minimal synchronous event bus for decoupled systems.
// Systems publish facts ("weapon:fired", "player:landed") and others react,
// without importing each other.

export class EventBus {
  constructor() {
    /** @type {Map<string, Set<Function>>} */
    this._handlers = new Map();
  }

  /** Subscribe; returns an unsubscribe function. */
  on(type, handler) {
    let set = this._handlers.get(type);
    if (!set) {
      set = new Set();
      this._handlers.set(type, set);
    }
    set.add(handler);
    return () => this.off(type, handler);
  }

  once(type, handler) {
    const off = this.on(type, (payload) => {
      off();
      handler(payload);
    });
    return off;
  }

  off(type, handler) {
    const set = this._handlers.get(type);
    if (set) {
      set.delete(handler);
      if (set.size === 0) this._handlers.delete(type);
    }
  }

  emit(type, payload) {
    const set = this._handlers.get(type);
    if (!set) return 0;
    // Copy so handlers may unsubscribe while being dispatched.
    const list = Array.from(set);
    for (const h of list) {
      try {
        h(payload);
      } catch (err) {
        // One faulty listener must not break the others or the game loop.
        console.error(`[events] handler for "${type}" failed:`, err);
      }
    }
    return list.length;
  }

  clear() {
    this._handlers.clear();
  }

  listenerCount(type) {
    const set = this._handlers.get(type);
    return set ? set.size : 0;
  }
}
