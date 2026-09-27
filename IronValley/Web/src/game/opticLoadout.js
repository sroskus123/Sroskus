// Optic loadout of one combatant (player or bot, same rules): the optic on the IV-7 rail, one spare optic in
// the backpack and the timed field swap. Pure logic on the fixed tick (no three.js, no DOM): Node-testable.
//
//   kit      what the combatant chose (loadout screen / armory crate): { optic, spare }. Respawn restores it.
//   mounted  optic on the rail now ('irons' = none, the flip-up irons are up); spare: optic id or null.
//   swap     backpack swap in progress: exchanges mounted <-> spare after attachments.swap.durationS. During
//            it (and the short raise after an interruption) the rifle cannot fire, reload or aim (the owner
//            puts the core lock 'other' on it while `busy`). It commits only at the end; an interruption
//            leaves the old optic mounted. Phase events at the data-driven fractions are hooks for the arms
//            animation (lower -> detach -> stow -> attach -> raise).
//
// Events (returned by tick / startSwap / cancel, the owner publishes them on the bus with its id):
//   optic:swap_started     { from, to, duration }
//   optic:swap_phase       { phase, t }                        phase in lower | detach | stow | attach | raise
//   optic:swap_finished    { mounted, spare }
//   optic:swap_interrupted { reason, mounted, spare, progress } reason in swapKey | sprint | switch | traverse | death | damage | reset | armory
//   optic:changed          { mounted, spare, source }           source in swap | armory | loadout | spawn

import attachments from '../data/attachments.json' with { type: 'json' };
import { IRONS, validateOpticLoadout } from '../weapons/optics.js';

const PHASE_ORDER = ['lower', 'detach', 'stow', 'attach', 'raise'];

export class OpticLoadout {
  /**
   * @param {object} [o]
   * @param {object} [o.kit]   { optic, spare } (validated; invalid -> attachments.loadoutDefault)
   * @param {object} [o.rules] attachments.swap override (tests)
   */
  constructor({ kit = null, rules = null } = {}) {
    this.rules = { ...attachments.swap, ...(rules || {}) };
    this.rules.phases = { ...attachments.swap.phases, ...((rules && rules.phases) || {}) };
    this.rules.interruptOn = { ...attachments.swap.interruptOn, ...((rules && rules.interruptOn) || {}) };
    const v = validateOpticLoadout(kit || attachments.loadoutDefault);
    const d = validateOpticLoadout(attachments.loadoutDefault);
    this.kit = v.ok ? { optic: v.optic, spare: v.spare } : { optic: d.optic, spare: d.spare };
    this.mounted = this.kit.optic;
    this.spare = this.kit.spare;
    this.swap = null; // { t, duration, from, to, phase }
    this.raise = 0; // seconds of weapon raise left after an interrupted swap (still locked)
    this.swapsCompleted = 0;
    this.swapsInterrupted = 0;
    this.changes = 0;
  }

  /** Swap running or the weapon still being raised after an interruption: no fire / reload / ADS. */
  get busy() {
    return !!this.swap || this.raise > 0;
  }

  get swapping() {
    return !!this.swap;
  }

  /** 0..1 progress of the running swap (0 when none). */
  get progress() {
    return this.swap ? Math.min(1, this.swap.t / this.swap.duration) : 0;
  }

  /** What the first-person view shows on the rail now (null while the rail is empty mid-swap). */
  get visualOptic() {
    const s = this.swap;
    if (!s) return this.mounted;
    const u = this.progress;
    const P = this.rules.phases;
    if (u < P.detach) return s.from;
    if (u < P.attach) return null;
    return s.to;
  }

  /** Something to exchange (an optic on the rail or in the backpack). */
  canSwapItems() {
    return this.mounted !== IRONS || this.spare !== null;
  }

  /**
   * Why a swap cannot start now (null = it can).
   * @param {object} ctx { alive, activeSlot, switching, reloading, sprinting, handsBusy }
   */
  swapBlockedReason(ctx = {}) {
    if (this.swap) return 'already_swapping';
    if (this.raise > 0) return 'raising';
    if (ctx.alive === false) return 'dead';
    if (!this.canSwapItems()) return 'nothing_to_swap';
    if ((ctx.activeSlot ?? 0) !== 0) return 'primary_not_active';
    if (ctx.switching) return 'switching';
    if (ctx.reloading) return 'reloading';
    if (ctx.sprinting) return 'sprinting';
    if (ctx.handsBusy) return 'hands_busy';
    return null;
  }

  /** Starts the backpack swap. Returns { ok, reason, events }. */
  startSwap(ctx = {}) {
    const reason = this.swapBlockedReason(ctx);
    if (reason) return { ok: false, reason, events: [] };
    const to = this.spare === null ? IRONS : this.spare;
    this.swap = { t: 0, duration: Math.max(1e-3, this.rules.durationS), from: this.mounted, to, phase: 'lower' };
    return {
      ok: true,
      reason: null,
      events: [
        { type: 'optic:swap_started', from: this.mounted, to, duration: this.swap.duration },
        { type: 'optic:swap_phase', phase: 'lower', t: 0 },
      ],
    };
  }

  /** Interrupts the running swap (nothing changes on the rail). Returns the events. */
  cancel(reason = 'swapKey') {
    if (!this.swap) return [];
    const progress = this.progress;
    this.swap = null;
    this.raise = Math.max(0, this.rules.interruptRaiseS || 0);
    this.swapsInterrupted++;
    return [{ type: 'optic:swap_interrupted', reason, mounted: this.mounted, spare: this.spare, progress }];
  }

  /**
   * One fixed tick. ctx: { alive, sprinting, switchRequested, handsBusy, damaged, swapPressed }.
   * Returns the events of this tick (interruption, phases, finish, change).
   */
  tick(dt, ctx = {}) {
    const ev = [];
    const I = this.rules.interruptOn;
    if (this.swap) {
      let reason = null;
      if (ctx.alive === false) reason = 'death';
      else if (ctx.swapPressed && I.swapKey) reason = 'swapKey';
      else if (ctx.switchRequested && I.switch) reason = 'switch';
      else if (ctx.sprinting && I.sprint) reason = 'sprint';
      else if (ctx.handsBusy && I.traverse) reason = 'traverse';
      else if (ctx.damaged && I.damage) reason = 'damage';
      if (reason) {
        ev.push(...this.cancel(reason));
        if (reason === 'death') this.raise = 0;
        return ev;
      }
      const s = this.swap;
      const u0 = s.t / s.duration;
      s.t += dt;
      const u1 = Math.min(1, s.t / s.duration);
      const P = this.rules.phases;
      for (const ph of PHASE_ORDER) {
        const at = P[ph];
        if (ph !== 'lower' && at > u0 && at <= u1) {
          s.phase = ph;
          ev.push({ type: 'optic:swap_phase', phase: ph, t: at * s.duration });
        }
      }
      if (s.t >= s.duration - 1e-9) {
        const from = s.from;
        this.mounted = s.to;
        this.spare = from === IRONS ? null : from;
        this.swap = null;
        this.swapsCompleted++;
        this.changes++;
        ev.push({ type: 'optic:swap_finished', mounted: this.mounted, spare: this.spare });
        ev.push({ type: 'optic:changed', mounted: this.mounted, spare: this.spare, source: 'swap' });
      }
    } else if (this.raise > 0) {
      this.raise = Math.max(0, this.raise - dt);
    }
    return ev;
  }

  /**
   * New kit (loadout screen or armory crate): applied at once; a running swap is cancelled first.
   * Returns { ok, reason, events }.
   */
  setKit({ optic, spare = null }, source = 'loadout') {
    const v = validateOpticLoadout({ optic, spare });
    if (!v.ok) return { ok: false, reason: v.reason, events: [] };
    const events = this.swap ? this.cancel(source === 'armory' ? 'armory' : 'reset') : [];
    this.raise = 0;
    this.kit = { optic: v.optic, spare: v.spare };
    this.mounted = v.optic;
    this.spare = v.spare;
    this.changes++;
    events.push({ type: 'optic:changed', mounted: this.mounted, spare: this.spare, source });
    return { ok: true, reason: null, events };
  }

  /** Respawn / new round: back to the kit, no swap. Returns the events. */
  resetToKit(source = 'spawn') {
    const events = this.swap ? this.cancel('reset') : [];
    this.raise = 0;
    const changed = this.mounted !== this.kit.optic || this.spare !== this.kit.spare;
    this.mounted = this.kit.optic;
    this.spare = this.kit.spare;
    if (changed) {
      this.changes++;
      events.push({ type: 'optic:changed', mounted: this.mounted, spare: this.spare, source });
    }
    return events;
  }

  getState() {
    return {
      kit: { ...this.kit },
      mounted: this.mounted,
      spare: this.spare,
      visual: this.visualOptic,
      busy: this.busy,
      swapping: this.swapping,
      progress: this.progress,
      swap: this.swap ? { from: this.swap.from, to: this.swap.to, t: this.swap.t, duration: this.swap.duration, phase: this.swap.phase } : null,
      raise: this.raise,
      swapsCompleted: this.swapsCompleted,
      swapsInterrupted: this.swapsInterrupted,
    };
  }
}
