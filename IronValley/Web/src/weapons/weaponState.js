// Engine-side handle of one weapon. The AUTHORITATIVE ammo / cadence / reload state machine is the
// rules core (src/core/weapon.js, shared with the C++ core and its test vectors): magazine + separate
// chamber + reserve, fire interval from accumulated integer microseconds, reload commits, interrupts and
// disable locks (life / sprint / switch / menu / results). This handle only adds what the core does not
// own: the ADS blend, the last trigger input, cumulative engine counters and a test-only infinite-ammo
// switch. It never changes ammo itself except through the core API.

import { WeaponState as CoreWeaponState } from '../core/weapon.js';
import { TickClock } from '../core/time.js';

export class WeaponHandle {
  /**
   * @param {object} o
   * @param {object} o.def    weapons.json entry (adsTime, ...)
   * @param {CoreWeaponState} [o.core] core weapon (from Match/RespawnSystem); created standalone from o.rulesDef if absent
   * @param {object} [o.rulesDef] compiled rules.weapons[id] (needed when o.core is absent)
   */
  constructor({ def, core = null, rulesDef = null }) {
    this.def = def;
    this.core = core || new CoreWeaponState(rulesDef);
    this.rulesDef = this.core.def;
    this.clock = new TickClock(); // standalone use only (callers normally pass dtUs)
    this.triggerHeld = false;
    this.adsHeld = false;
    this.ads = 0; // 0 = hip, 1 = fully aimed
    this.shotsFired = 0; // cumulative for the engine (core counters reset on respawn / refill)
    this.infiniteAmmo = false; // debug / test only
    this.lastEvents = [];
  }

  get magazine() {
    return this.core.magazine;
  }
  get chamber() {
    return this.core.chamber;
  }
  get reserve() {
    return this.core.reserve;
  }
  /** 'ready' | 'reloading' | 'chambering' */
  get state() {
    return this.core.state;
  }
  get enabled() {
    return this.core.enabled;
  }
  get dryFires() {
    return this.core.dryFires;
  }
  get reloadsCompleted() {
    return this.core.reloadsCompleted;
  }
  get fireIntervalSeconds() {
    return this.rulesDef.fireIntervalUs / 1e6;
  }
  totalAmmo() {
    return this.core.totalAmmo;
  }

  /** Duration of the running action (reload / chambering) in microseconds, 0 when ready. */
  actionDurationUs() {
    const c = this.core;
    const d = this.rulesDef;
    if (c.state === 'chambering') return d.chamber.durationUs;
    if (c.state === 'reloading') return c.reloadKind === 'empty' ? d.empty.durationUs : d.tactical.durationUs;
    return 0;
  }

  /** Progress 0..1 of the running reload / chambering action. */
  get reloadProgress() {
    const dur = this.actionDurationUs();
    return dur > 0 ? Math.min(1, this.core.actionUs / dur) : 0;
  }

  /** Reload request -> core result string (started_tactical / started_empty / started_chamber / rejected_*). */
  reload() {
    return this.core.reload();
  }

  /**
   * One fixed tick. Returns the number of rounds fired; for each round `onShot(i)` is called.
   * The core is updated every tick with the real trigger state, also while locked (core contract).
   * @param {number} dt  seconds (ADS blend)
   * @param {object} inp { trigger, ads, sprinting, dtUs? }
   */
  tick(dt, inp, onShot = null) {
    const dtUs = Number.isSafeInteger(inp.dtUs) ? inp.dtUs : this.clock.advance(dt);
    const trigger = !!inp.trigger;
    this.triggerHeld = trigger;
    const c = this.core;
    this.adsHeld = !!inp.ads && c.state === 'ready' && !inp.sprinting && !c.disabledBy.includes('switch') && !c.disabledBy.includes('life');
    const target = this.adsHeld ? 1 : 0;
    const rate = dt / Math.max(this.def.adsTime || 0.2, 1e-3);
    this.ads = this.ads < target ? Math.min(target, this.ads + rate) : Math.max(target, this.ads - rate);

    if (this.infiniteAmmo && c.state === 'ready') {
      const cap = this.rulesDef.magazineCapacity;
      if (c.magazine < cap || (this.rulesDef.hasChamber && c.chamber === 0)) {
        c.setAmmo({ magazine: cap, chamber: this.rulesDef.hasChamber ? 1 : 0, reserve: c.reserve });
      }
    }
    const shots = c.update(dtUs, trigger);
    for (let i = 0; i < shots; i++) {
      this.shotsFired++;
      if (onShot) onShot(i);
    }
    this.lastEvents = c.takeEvents();
    return shots;
  }

  /** Releases trigger / ADS input (menu, focus loss, death). The core sees the release on its next update. */
  releaseInputs() {
    this.triggerHeld = false;
    this.adsHeld = false;
  }

  /**
   * A menu opened over the game (the core 'menu' lock is already set, the simulation stops behind the menu).
   * Shows the core the trigger release now and lets the fire interval that is still running finish: the core
   * lets time run while a lock is on, the menu lock already interrupted any reload, and one cycle (<= 80 ms
   * for the rifle) is far shorter than any real pause. Without this the cycle stayed frozen mid-way through
   * the pause, and a quick click after "Pokračovat" shorter than the leftover (up to one full interval) was
   * swallowed. The first press after the menu now fires at once, a button kept down still needs a new press.
   */
  settleForMenu() {
    this.releaseInputs();
    const c = this.core;
    c.update(c.state === 'ready' ? c.cooldownUs : 0, false);
  }

  /** Test helper: full magazine + chamber + start reserve through the core (interrupts a reload). */
  refill() {
    this.core.resetToLoadout();
    this.lastEvents = this.core.takeEvents();
  }

  getState() {
    const c = this.core;
    return {
      id: this.def.id,
      rulesId: this.rulesDef.id,
      name: this.def.displayName,
      state: c.state,
      reloadKind: c.reloadKind,
      magazine: c.magazine,
      chamber: c.chamber,
      reserve: c.reserve,
      capacity: this.rulesDef.magazineCapacity,
      fireMode: c.fireMode,
      reloadProgress: this.reloadProgress,
      triggerHeld: this.triggerHeld,
      adsHeld: this.adsHeld,
      ads: this.ads,
      enabled: c.enabled,
      disabledBy: c.disabledBy,
      shotsFired: this.shotsFired,
      coreShotsFired: c.shotsFired,
      dryFires: c.dryFires,
      reloadsStarted: c.reloadsStarted,
      reloadsCompleted: c.reloadsCompleted,
      reloadsInterrupted: c.reloadsInterrupted,
      chamberActions: c.chamberActions,
      fireInterval: this.fireIntervalSeconds,
      infiniteAmmo: this.infiniteAmmo,
    };
  }
}

// Backwards-compatible name: the engine weapon state IS the core state machine behind a handle.
export { WeaponHandle as WeaponState };
