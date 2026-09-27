// Weapon state machine (pure logic, no rendering): fire cadence from accumulated simulation
// time (decision D8), magazine / reserve accounting, reload as a single authoritative
// transition, ADS blend. Ticked on the fixed simulation step only.
//
// NOTE: the shared rules core (src/core, owned by another module) will become the
// authoritative ammo implementation; this class keeps the same semantics (no chamber
// round, reload moves min(missing, reserve) rounds exactly once).

export class WeaponState {
  constructor(def) {
    this.def = def;
    this.interval = 60 / def.rpm;
    this.magazine = def.magazineSize;
    this.reserve = def.reserveAmmo;
    this.state = 'ready'; // 'ready' | 'reloading'
    this.reloadTimer = 0;
    this.reloadDuration = 0;
    this.reloadEmpty = false;
    this.simTime = 0; // time at the start of the current tick
    this.nextShotTime = 0;
    this.triggerHeld = false;
    this.adsHeld = false;
    this.ads = 0; // 0 = hip, 1 = fully aimed
    this.firingStreak = false;
    this.shotsFired = 0;
    this.dryFires = 0;
    this.reloadsCompleted = 0;
    this.infiniteAmmo = false; // debug / test only
    this.lastShotTick = -1;
    this.ticks = 0;
  }

  get fireIntervalSeconds() {
    return this.interval;
  }

  canReload() {
    return this.state === 'ready' && this.magazine < this.def.magazineSize && this.reserve > 0;
  }

  startReload() {
    if (!this.canReload()) return false;
    this.state = 'reloading';
    this.reloadEmpty = this.magazine === 0;
    this.reloadDuration = this.reloadEmpty ? this.def.reloadEmptyTime : this.def.reloadTime;
    this.reloadTimer = 0;
    return true;
  }

  /** Cancels a reload in progress without changing ammo (e.g. respawn / weapon switch). */
  cancelReload() {
    if (this.state !== 'reloading') return;
    this.state = 'ready';
    this.reloadTimer = 0;
  }

  /**
   * Advances one fixed tick.
   * @param {number} dt
   * @param {{trigger:boolean, ads:boolean, reload:boolean, canFire:boolean, sprinting:boolean}} inp
   * @param {(shotIndex:number)=>void} onShot  called for each round fired this tick
   * @returns {number} rounds fired this tick
   */
  tick(dt, inp, onShot) {
    const t = this.simTime;
    let fired = 0;
    const freshPress = inp.trigger && !this.triggerHeld;
    this.triggerHeld = !!inp.trigger;
    this.adsHeld = !!inp.ads && this.state !== 'reloading' && !inp.sprinting;

    // ADS blend
    const target = this.adsHeld ? 1 : 0;
    const rate = dt / Math.max(this.def.adsTime, 1e-3);
    this.ads = this.ads < target ? Math.min(target, this.ads + rate) : Math.max(target, this.ads - rate);

    if (inp.reload) this.startReload();

    // reload progress: ammo transfers exactly once, when the reload completes
    if (this.state === 'reloading') {
      this.reloadTimer += dt;
      if (this.reloadTimer >= this.reloadDuration - 1e-9) {
        const moved = Math.min(this.def.magazineSize - this.magazine, this.reserve);
        this.magazine += moved;
        this.reserve -= moved;
        this.state = 'ready';
        this.reloadTimer = 0;
        this.reloadsCompleted++;
      }
    }

    const able = this.state === 'ready' && inp.canFire !== false;
    if (this.triggerHeld && able) {
      if (!this.firingStreak) {
        // fresh burst: cannot fire earlier than the cadence allows, but no stored-up shots
        if (this.nextShotTime < t) this.nextShotTime = t;
      }
      while (t >= this.nextShotTime - 1e-9) {
        if (this.magazine <= 0 && !this.infiniteAmmo) {
          if (freshPress) {
            this.dryFires++;
            if (this.reserve > 0) this.startReload();
          }
          break;
        }
        if (!this.infiniteAmmo) this.magazine--;
        this.shotsFired++;
        fired++;
        this.lastShotTick = this.ticks;
        if (onShot) onShot(fired - 1);
        this.nextShotTime += this.interval;
      }
      this.firingStreak = true;
    } else {
      this.firingStreak = false;
    }

    this.simTime += dt;
    this.ticks++;
    return fired;
  }

  /** Releases trigger/ADS immediately (menu, focus loss, death). */
  releaseInputs() {
    this.triggerHeld = false;
    this.adsHeld = false;
    this.firingStreak = false;
  }

  totalAmmo() {
    return this.magazine + this.reserve;
  }

  getState() {
    return {
      id: this.def.id,
      state: this.state,
      magazine: this.magazine,
      reserve: this.reserve,
      reloadProgress: this.state === 'reloading' ? this.reloadTimer / this.reloadDuration : 0,
      triggerHeld: this.triggerHeld,
      adsHeld: this.adsHeld,
      ads: this.ads,
      shotsFired: this.shotsFired,
      dryFires: this.dryFires,
      reloadsCompleted: this.reloadsCompleted,
      fireInterval: this.interval,
      infiniteAmmo: this.infiniteAmmo,
    };
  }
}
