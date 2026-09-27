// Game audio (WebAudio): recorded / processed sound files (Tools/audio/build_audio.py, provenance in
// Shared/audio/SOURCES.md) played by REAL game events on the event bus:
//   weapon:fired       close / distant take by listener distance (cross-fade), outdoor tail, propagation delay,
//                      near-miss crack / whiz when the bullet passes close to the listener
//   weapon:reload_*    magazine out (timed after the start, cancelled by an interruption); weapon:action ->
//                      magazine in, bolt / slide release, charging handle / slide pull (core commit moments)
//   weapon:dry_fire, weapon:switched, weapon:hit (impact by surface), weapon:casing_landed
//   footstep           { surface, loudness, speed, kind: 'step' | 'land' }, player:jump, traverse:start
//   game:state         ambience (wind bed + distant birds) only while playing; any other state stops everything
//   combatant:died     stops that combatant's steps / reload / movement sounds; round:reset / reset() stop all
// Every sound is a one-shot started by an event, except the wind bed (a loop that exists only while playing),
// so stopping fire, dying, pausing or restarting never leaves a sound running. Remote sounds are spatialised
// (HRTF PannerNode, inverse distance), low-passed when the listener has no line of sight (small raycast budget)
// and limited per category / per owner. Master bus: volume -> compressor -> limiter -> soft clipper.
//
// The AudioContext is created on the first user gesture (menu click, autoplay policy); files are fetched
// earlier (prefetch) and decoded then. Without WebAudio the system stays silent and does nothing.

import config from '../data/audio.json' with { type: 'json' };
import bank from '../data/audio_bank.json' with { type: 'json' };

const LN10_20 = Math.LN10 / 20;
const dbToGain = (db) => Math.exp(db * LN10_20);

/** Plain {x, y, z} from a Vector3, an array or an object. */
export function vec(p, out = { x: 0, y: 0, z: 0 }) {
  if (!p) return null;
  if (Array.isArray(p)) {
    out.x = p[0];
    out.y = p[1];
    out.z = p[2];
  } else {
    out.x = p.x;
    out.y = p.y;
    out.z = p.z;
  }
  return out;
}

export function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

/**
 * Closest approach of the segment a -> b to point p.
 * @returns {{ t: number, distance: number, along: number, point: {x,y,z} }} t in [0, 1], along = metres from a
 */
export function closestApproach(a, b, p) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dz = b.z - a.z;
  const len2 = dx * dx + dy * dy + dz * dz;
  let t = len2 > 1e-12 ? ((p.x - a.x) * dx + (p.y - a.y) * dy + (p.z - a.z) * dz) / len2 : 0;
  t = Math.min(1, Math.max(0, t));
  const point = { x: a.x + dx * t, y: a.y + dy * t, z: a.z + dz * t };
  return { t, distance: dist(point, p), along: Math.sqrt(len2) * t, point };
}

/** Other shooters: weights of the close / distant takes at distance d (linear cross-fade). */
export function shotLayerWeights(d, s = config.shots) {
  if (d <= s.closeFullUntil) return { close: 1, distant: 0 };
  if (d >= s.distantOnlyFrom) return { close: 0, distant: 1 };
  const u = (d - s.closeFullUntil) / (s.distantOnlyFrom - s.closeFullUntil);
  return { close: 1 - u, distant: u };
}

/** Air absorption low-pass cut-off for distance d. */
export function airCutoff(d, s = config.shots) {
  return Math.max(s.minCutoff, Math.min(20000, 20000 * Math.exp(-d / s.airAbsorptionMeters)));
}

/** Compressor make-up gain applied automatically by WebAudio's DynamicsCompressorNode (spec: (1/fullRangeGain)^0.6). */
export function compressorMakeup(c) {
  const fullRangeDb = c.threshold + (0 - c.threshold) / c.ratio;
  return Math.pow(1 / dbToGain(fullRangeDb), 0.6);
}

function softClipCurve(n = 2048) {
  // linear up to 0.8, then a tanh knee that never exceeds 1.0
  const curve = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    const a = Math.abs(x);
    const y = a <= 0.8 ? a : 0.8 + 0.2 * Math.tanh((a - 0.8) / 0.2);
    curve[i] = Math.sign(x) * y;
  }
  return curve;
}

function setPos(node, prefix, p) {
  if (node[prefix + 'X']) {
    node[prefix + 'X'].value = p.x;
    node[prefix + 'Y'].value = p.y;
    node[prefix + 'Z'].value = p.z;
  } else if (prefix === 'position' && node.setPosition) node.setPosition(p.x, p.y, p.z);
}

const _tmpA = { x: 0, y: 0, z: 0 };
const _tmpB = { x: 0, y: 0, z: 0 };

export class AudioSystem {
  /**
   * @param {object} o
   * @param {import('../engine/events.js').EventBus} o.events
   * @param {object} o.settings                 Settings (get('masterVolume'), onChange)
   * @param {(id: string) => boolean} o.isPlayer local player's combatant id test
   * @param {(origin, dir, far) => object|null} [o.raycast]  static-world raycast for occlusion (Vector3-like args)
   * @param {() => object} [o.createVector]      factory for the raycast origin / direction objects (Vector3)
   * @param {() => AudioContext} [o.createContext]
   * @param {(url: string) => Promise<ArrayBuffer>} [o.fetchBuffer]
   * @param {(path: string) => boolean} [o.hasAsset]
   * @param {(id: string) => object|null} [o.combatantPosition]  position of a combatant (remote reload / switch sounds)
   * @param {() => number} [o.random]
   * @param {object} [o.config] [o.bank]         overrides (tests)
   */
  constructor(o) {
    this.events = o.events;
    this.settings = o.settings;
    this.isPlayer = o.isPlayer || (() => false);
    this.raycast = o.raycast || null;
    this.createVector = o.createVector || (() => ({ x: 0, y: 0, z: 0, copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; } }));
    this.createContext = o.createContext || defaultContextFactory;
    this.fetchBuffer = o.fetchBuffer || defaultFetch;
    this.hasAsset = o.hasAsset || (() => true);
    this.combatantPosition = o.combatantPosition || null;
    this.random = o.random || Math.random;
    this.cfg = o.config || config;
    this.bank = o.bank || bank;

    this.ctx = null;
    this.enabled = true;
    this.playing = false; // game state 'playing'
    this.listener = { x: 0, y: 0, z: 0 };
    this.encoded = new Map(); // file -> ArrayBuffer (prefetched)
    this.buffers = new Map(); // file -> { buffer, offset }
    this.voices = []; // active voices
    this.lastVariation = new Map();
    this.wind = null;
    this.birdTimer = 0;
    this.simTime = 0;
    this._occCache = new Map();
    this._raysThisTick = 0;
    this._voiceSeq = 0;
    this._rayO = this.createVector();
    this._rayD = this.createVector();
    this.stats = {
      played: 0,
      byKey: {},
      byCategory: {},
      stolen: 0,
      stoppedByReset: 0,
      skippedNoBuffer: 0,
      skippedFar: 0,
      nearMisses: 0,
      occlusionRaycasts: 0,
      occluded: 0,
      decoded: 0,
      decodeErrors: 0,
      fetched: 0,
      fetchErrors: 0,
      hitmarkers: 0,
    };
    this.log = [];
    this._offs = [];
    this._subscribe();
    if (this.settings && this.settings.onChange) {
      this._offs.push(
        this.settings.onChange((key) => {
          if (key === 'masterVolume' || key === '*') this._applyVolume();
        }),
      );
    }
  }

  // ------------------------------------------------------------------ lifecycle

  /** All sound files named by the bank. */
  files() {
    const out = [];
    for (const list of Object.values(this.bank.sounds)) for (const f of list) out.push(f);
    return out;
  }

  url(file) {
    return (this.bank.basePath || 'assets/audio/') + file;
  }

  /** Fetches the encoded files (no AudioContext needed). Resolves when all requests finished. */
  prefetch() {
    if (this._prefetch) return this._prefetch;
    const jobs = [];
    for (const f of this.files()) {
      if (!this.hasAsset(this.url(f)) || this.encoded.has(f)) continue;
      jobs.push(
        this.fetchBuffer(this.url(f))
          .then((ab) => {
            this.encoded.set(f, ab);
            this.stats.fetched++;
            if (this.ctx) return this._decode(f);
            return null;
          })
          .catch(() => {
            this.stats.fetchErrors++;
          }),
      );
    }
    this._prefetch = Promise.all(jobs);
    return this._prefetch;
  }

  /** Call from a user gesture (menu click). Creates / resumes the AudioContext. Safe to call repeatedly. */
  unlock() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended' && this.ctx.resume) this.ctx.resume().catch(() => {});
      return true;
    }
    let ctx = null;
    try {
      ctx = this.createContext();
    } catch {
      ctx = null;
    }
    if (!ctx) return false;
    this.ctx = ctx;
    this._buildMaster();
    for (const f of this.encoded.keys()) this._decode(f);
    if (!this._prefetch) this.prefetch();
    if (ctx.state === 'suspended' && ctx.resume) ctx.resume().catch(() => {});
    if (this.playing) this._startAmbience();
    return true;
  }

  get ready() {
    return !!this.ctx && this.buffers.size > 0;
  }

  _decode(f) {
    const ab = this.encoded.get(f);
    if (!ab || this.buffers.has(f) || !this.ctx) return null;
    this.encoded.delete(f);
    let p;
    try {
      p = this.ctx.decodeAudioData(ab.slice ? ab.slice(0) : ab);
    } catch (e) {
      this.stats.decodeErrors++;
      return null;
    }
    return Promise.resolve(p)
      .then((buffer) => {
        this.buffers.set(f, { buffer, offset: this._leadIn(buffer) });
        this.stats.decoded++;
        if (this.playing && !this.wind && this._isWindFile(f)) this._startAmbience();
      })
      .catch(() => {
        this.stats.decodeErrors++;
      });
  }

  _isWindFile(f) {
    const w = this.bank.sounds[this.cfg.ambience.wind] || [];
    return w.includes(f);
  }

  /**
   * Encoder / decoder lead-in (MP3 priming samples when a browser does not strip them): seconds of silence
   * before the first sample within leadInTrimDb of the peak, minus 3 ms, capped at 60 ms.
   */
  _leadIn(buffer) {
    if (!buffer || !buffer.getChannelData) return 0;
    const d = buffer.getChannelData(0);
    const n = Math.min(d.length, Math.floor(buffer.sampleRate * 0.2));
    let peak = 0;
    for (let i = 0; i < d.length; i++) peak = Math.max(peak, Math.abs(d[i]));
    if (peak <= 0) return 0;
    const thr = peak * dbToGain(this.cfg.leadInTrimDb);
    let i = 0;
    while (i < n && Math.abs(d[i]) < thr) i++;
    const s = i / buffer.sampleRate - 0.003;
    return s > 0 && s < 0.06 ? s : 0;
  }

  _buildMaster() {
    const c = this.ctx;
    const mc = this.cfg.masterChain;
    this.master = c.createGain();
    this.compressor = c.createDynamicsCompressor();
    this.limiter = c.createDynamicsCompressor();
    for (const [node, p] of [
      [this.compressor, mc.compressor],
      [this.limiter, mc.limiter],
    ]) {
      node.threshold.value = p.threshold;
      node.knee.value = p.knee;
      node.ratio.value = p.ratio;
      node.attack.value = p.attack;
      node.release.value = p.release;
    }
    // cancel the automatic make-up gain so levels below the threshold are unchanged
    this.trim = c.createGain();
    this.trim.gain.value = 1 / (compressorMakeup(mc.compressor) * compressorMakeup(mc.limiter));
    this.master.connect(this.compressor);
    this.compressor.connect(this.limiter);
    this.limiter.connect(this.trim);
    let last = this.trim;
    if (mc.softClip && c.createWaveShaper) {
      this.clipper = c.createWaveShaper();
      this.clipper.curve = softClipCurve();
      this.clipper.oversample = '2x';
      last.connect(this.clipper);
      last = this.clipper;
    }
    last.connect(c.destination);
    this.buses = {};
    for (const [name, cat] of Object.entries(this.cfg.categories)) {
      const g = c.createGain();
      g.gain.value = cat.gain;
      g.connect(this.master);
      this.buses[name] = g;
    }
    this._applyVolume();
  }

  _applyVolume() {
    if (!this.master) return;
    const v = this.settings ? this.settings.get('masterVolume') : 1;
    this.master.gain.value = v;
  }

  get masterGain() {
    return this.master ? this.master.gain.value : this.settings ? this.settings.get('masterVolume') : 1;
  }

  dispose() {
    this.stopAll('dispose');
    for (const off of this._offs) off();
    this._offs = [];
  }

  // ------------------------------------------------------------------ listener / time

  /** Listener at the camera (position + forward / up vectors). */
  setListener(pos, forward, up) {
    vec(pos, this.listener);
    if (!this.ctx) return;
    const L = this.ctx.listener;
    const t = this.ctx.currentTime;
    if (L.positionX) {
      L.positionX.setValueAtTime(pos.x, t);
      L.positionY.setValueAtTime(pos.y, t);
      L.positionZ.setValueAtTime(pos.z, t);
      L.forwardX.setValueAtTime(forward.x, t);
      L.forwardY.setValueAtTime(forward.y, t);
      L.forwardZ.setValueAtTime(forward.z, t);
      L.upX.setValueAtTime(up.x, t);
      L.upY.setValueAtTime(up.y, t);
      L.upZ.setValueAtTime(up.z, t);
    } else if (L.setPosition) {
      L.setPosition(pos.x, pos.y, pos.z);
      L.setOrientation(forward.x, forward.y, forward.z, up.x, up.y, up.z);
    }
  }

  /** Simulation tick (only while playing): raycast budget, distant birds. */
  tick(dt) {
    this.simTime += dt;
    this._raysThisTick = 0;
    this._pruneEnded();
    if (!this.playing || !this.ctx) return;
    const a = this.cfg.ambience;
    this.birdTimer -= dt;
    if (this.birdTimer <= 0) {
      this.birdTimer = this._rand(a.birdInterval[0], a.birdInterval[1]);
      if (this.wind) this._bird();
    }
  }

  // ------------------------------------------------------------------ events

  _subscribe() {
    const ev = this.events;
    if (!ev) return;
    const on = (name, fn) => this._offs.push(ev.on(name, fn));
    on('weapon:fired', (p) => this.onFired(p));
    on('weapon:hit', (p) => this.onHit(p));
    on('weapon:dry_fire', (p) => this._weaponOneShot(p.id, p.weaponId, 'dry', null));
    on('weapon:reload_started', (p) => this.onReloadStarted(p));
    on('weapon:reload_interrupted', (p) => this.stopOwner(p.id, ['mech']));
    on('weapon:action', (p) => this.onAction(p));
    on('weapon:switched', (p) => this.onSwitched(p));
    on('weapon:casing_landed', (p) => this.onCasing(p));
    on('footstep', (p) => this.onFootstep(p));
    on('player:jump', () => this._play(this.cfg.movement.jump, { category: 'movement', owner: this._playerOwner() }));
    on('traverse:start', (p) => this._ownedOneShot(p.id, this.cfg.movement.traverse, 'movement', p.ledgePoint));
    on('combatant:died', (p) => this.stopOwner(p.victimId, ['step', 'mech', 'movement']));
    on('round:reset', () => {
      this.stopAll('round-reset');
      if (this.playing) this._startAmbience();
    });
    on('game:state', (p) => this.onGameState(p.state));
  }

  onGameState(state) {
    const was = this.playing;
    this.playing = state === 'playing';
    if (this.playing && !was) {
      this.birdTimer = this._rand(this.cfg.ambience.birdInterval[0], this.cfg.ambience.birdInterval[1]);
      this._startAmbience();
    } else if (!this.playing) this.stopAll(`state:${state}`);
  }

  /** New session / level: stop everything (the next 'playing' state restarts the ambience). */
  reset() {
    this.stopAll('reset');
    if (this.playing) this._startAmbience();
  }

  _playerOwner() {
    return '__player__';
  }

  _ownerOf(id) {
    return this.isPlayer(id) ? this._playerOwner() : id;
  }

  onFired(p) {
    const w = this.cfg.weapons[p.weaponId];
    if (!w || !p.muzzle) return;
    const muzzle = vec(p.muzzle, { x: 0, y: 0, z: 0 });
    const own = this.isPlayer(p.shooterId);
    const owner = this._ownerOf(p.shooterId);
    if (own) {
      this._play(w.close, { category: 'weapon', owner });
      this._play(w.tail, { category: 'tail', owner, delay: w.tailDelay });
      return;
    }
    const s = this.cfg.shots;
    const d = dist(muzzle, this.listener);
    if (d > s.maxAudible) {
      this.stats.skippedFar++;
      return;
    }
    const delay = d / s.speedOfSound;
    const occ = this._occlusion(muzzle);
    const cutoff = Math.min(airCutoff(d, s), occ.cutoff);
    const wts = shotLayerWeights(d, s);
    if (wts.close > 0) this._play(w.close, { category: 'weapon', owner, pos: muzzle, ref: s.closeRef, gain: wts.close * occ.gain, delay, cutoff });
    if (wts.distant > 0) this._play(w.distant, { category: 'weapon', owner, pos: muzzle, ref: s.distantRef, gain: wts.distant * occ.gain, delay, cutoff });
    // the valley answers from everywhere: tail is not panned, level falls with distance
    const tailGain = Math.min(1, Math.max(0.1, s.tailRef / Math.max(d, 1)));
    this._play(w.tail, { category: 'tail', owner, gain: tailGain, delay: delay + w.tailDelay, cutoff: Math.min(cutoff, 8000) });
    this._nearMiss(p, w, muzzle);
  }

  _nearMiss(p, w, muzzle) {
    if (!p.dir) return;
    const nm = this.cfg.nearMiss;
    let end = null;
    const hp = p.shot && p.shot.hitPoint;
    if (hp) end = vec(hp, _tmpB);
    else {
      const dir = vec(p.dir, _tmpA);
      const r = this.cfg.shots.range;
      end = { x: muzzle.x + dir.x * r, y: muzzle.y + dir.y * r, z: muzzle.z + dir.z * r };
    }
    const ca = closestApproach(muzzle, end, this.listener);
    if (ca.distance > nm.radius) return;
    // the bullet stopped before it reached the listener (hit something short of them)
    if (ca.t >= 1 && dist(end, this.listener) > nm.endMargin) return;
    if (ca.t <= 0) return; // listener behind the muzzle
    if (p.shot && p.shot.hitKind === 'combatant' && hp && dist(end, this.listener) < 1.2) return; // the listener was hit
    const gain = Math.max(nm.minGain, Math.min(1, this.cfg.refDistance.nearmiss / Math.max(ca.distance, 0.1)));
    const delay = ca.along / (w.bulletSpeed || 900) + ca.distance / this.cfg.shots.speedOfSound;
    this.stats.nearMisses++;
    this._play(w.nearMiss, { category: 'nearmiss', owner: this._ownerOf(p.shooterId), pos: ca.point, ref: this.cfg.refDistance.nearmiss, gain, delay });
  }

  onHit(p) {
    if (!p.point) return;
    // mapped surface of a world hit (WorldQuery) first, else the event's surface / raw level material
    const surf = (p.hit && p.hit.surface) || p.surface || (p.hit && p.hit.kind === 'combatant' ? 'flesh' : 'concrete');
    const S = this.cfg.surfaces;
    const key = S.impact[surf] || S.impact.default;
    const pos = vec(p.point, { x: 0, y: 0, z: 0 });
    const d = dist(pos, this.listener);
    if (d > this.cfg.maxDistance.impact) {
      this.stats.skippedFar++;
    } else {
      const occ = this._occlusion(pos);
      const cutoff = Math.min(S.impactCutoff[surf] || 20000, occ.cutoff, d > 30 ? airCutoff(d) : 20000);
      this._play(key, { category: 'impact', owner: this._ownerOf(p.shooterId), pos, ref: this.cfg.refDistance.impact, gain: occ.gain, cutoff, delay: d / this.cfg.shots.speedOfSound });
    }
    // hit confirmation for the local shooter (UI, not spatial)
    const dmg = p.damage;
    if (this.isPlayer(p.shooterId) && p.hit && p.hit.kind === 'combatant' && dmg && (dmg.result === 'applied' || dmg.result === 'killed')) this.hitmarker();
  }

  onReloadStarted(p) {
    const w = this.cfg.weapons[p.weaponId];
    if (!w || !w.magOut) return;
    this._weaponOneShot(p.id, p.weaponId, null, w.magOut.key, w.magOut.delay);
  }

  onAction(p) {
    const w = this.cfg.weapons[p.weaponId];
    if (!w) return;
    const key = w.actions[p.type];
    if (key) this._weaponOneShot(p.id, p.weaponId, null, key);
  }

  onSwitched(p) {
    const w = this.cfg.weapons[p.weaponId];
    this._ownedOneShot(p.id, this.cfg.switch.cloth, 'mech', null);
    if (w && w.draw) this._ownedOneShot(p.id, w.draw, 'mech', null, this.cfg.switch.drawDelay);
  }

  onCasing(p) {
    const w = this.cfg.weapons[p.weaponId];
    if (!w || !w.casing || !p.position) return;
    const pos = vec(p.position, { x: 0, y: 0, z: 0 });
    if (dist(pos, this.listener) > this.cfg.maxDistance.casing) return;
    const S = this.cfg.surfaces;
    const g = S.casingGain[p.surface] ?? S.casingGain.default;
    const soft = g < 0.6;
    this._play(w.casing, { category: 'casing', owner: p.shooterId ? this._ownerOf(p.shooterId) : null, pos, ref: this.cfg.refDistance.casing, gain: g, cutoff: soft ? S.casingSoftCutoff : 20000 });
  }

  onFootstep(p) {
    const S = this.cfg.surfaces;
    const F = this.cfg.footsteps;
    const key = S.step[p.surface] || S.step.default;
    const loud = Math.min(1, Math.max(0, p.loudness ?? 0.5));
    let gain = F.loudnessBase + (1 - F.loudnessBase) * loud;
    const land = p.kind === 'land';
    if (land) gain *= F.landGain;
    const own = this.isPlayer(p.id);
    const owner = this._ownerOf(p.id);
    let pos = null;
    let occ = { gain: 1, cutoff: 20000 };
    if (!own) {
      pos = vec(p.position, { x: 0, y: 0, z: 0 });
      if (!pos || dist(pos, this.listener) > this.cfg.maxDistance.step) {
        this.stats.skippedFar++;
        return;
      }
      occ = this._occlusion(pos);
    }
    const base = { category: 'step', owner, pos, ref: this.cfg.refDistance.step, cutoff: occ.cutoff };
    this._play(key, { ...base, gain: gain * occ.gain });
    if (land) {
      const [a, b] = F.landSecondFootDelay;
      this._play(key, { ...base, gain: gain * 0.8 * occ.gain, delay: this._rand(a, b), maxPerOwnerOverride: 3 });
      this._play(F.landThump, { ...base, category: 'movement', gain: loud * occ.gain });
    }
  }

  /** Weapon sound by weapon role (dry) or explicit key; own = not spatial. */
  _weaponOneShot(id, weaponId, role, key, delay = 0) {
    const w = this.cfg.weapons[weaponId];
    const k = key || (w && role ? w[role] : null);
    if (!k) return;
    this._ownedOneShot(id, k, 'mech', null, delay);
  }

  /** One-shot owned by combatant `id`: not spatial for the local player, else at the combatant. */
  _ownedOneShot(id, key, category, pos, delay = 0) {
    const own = this.isPlayer(id);
    const owner = this._ownerOf(id);
    if (own) return this._play(key, { category, owner, delay });
    const p = pos ? vec(pos, { x: 0, y: 0, z: 0 }) : this._combatantPos(id);
    if (!p) return null;
    const d = dist(p, this.listener);
    const maxD = this.cfg.maxDistance[category] ?? 60;
    if (d > maxD) {
      this.stats.skippedFar++;
      return null;
    }
    const occ = this._occlusion(p);
    return this._play(key, { category, owner, pos: p, ref: this.cfg.refDistance[category] ?? 2, gain: occ.gain, cutoff: occ.cutoff, delay });
  }

  /** Position of a combatant for its mechanical sounds (last known from its footsteps / fired shots). */
  _combatantPos(id) {
    return this.combatantPosition ? this.combatantPosition(id) : null;
  }

  hitmarker() {
    if (!this.ctx || !this.enabled || !this.playing) return;
    const h = this.cfg.hitmarker;
    const c = this.ctx;
    const t = c.currentTime;
    const o = c.createOscillator();
    o.type = 'triangle';
    o.frequency.setValueAtTime(h.f0, t);
    o.frequency.exponentialRampToValueAtTime(h.f1, t + h.duration);
    const g = c.createGain();
    g.gain.setValueAtTime(h.gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + h.duration);
    o.connect(g);
    g.connect(this.buses.ui);
    o.start(t);
    o.stop(t + h.duration + 0.02);
    this.stats.hitmarkers++;
    this._count('ui_hitmarker', 'ui');
  }

  // ------------------------------------------------------------------ ambience

  _startAmbience() {
    if (!this.ctx || this.wind) return;
    const a = this.cfg.ambience;
    const files = this.bank.sounds[a.wind] || [];
    const b = files.length ? this.buffers.get(files[0]) : null;
    if (!b) return;
    const c = this.ctx;
    const src = c.createBufferSource();
    src.buffer = b.buffer;
    src.loop = true;
    const dur = (this.bank.files[files[0]] && this.bank.files[files[0]].duration) || b.buffer.duration;
    src.loopStart = b.offset;
    src.loopEnd = Math.min(b.buffer.duration, b.offset + dur);
    const g = c.createGain();
    const t = c.currentTime;
    g.gain.value = 0;
    g.gain.setTargetAtTime(a.windGain, t, a.fadeIn / 3);
    src.connect(g);
    g.connect(this.buses.ambience);
    src.start(t, b.offset);
    const v = { id: ++this._voiceSeq, key: a.wind, file: files[0], category: 'ambience', owner: 'ambience', src, gain: g, start: t, end: Infinity, loop: true };
    this.wind = v;
    this.voices.push(v);
    this._count(a.wind, 'ambience', files[0], null);
  }

  _bird() {
    const a = this.cfg.ambience;
    const ang = this._rand(0, Math.PI * 2);
    const r = this._rand(a.birdDistance[0], a.birdDistance[1]);
    const L = this.listener;
    const pos = { x: L.x + Math.cos(ang) * r, y: L.y + this._rand(a.birdHeight[0], a.birdHeight[1]), z: L.z + Math.sin(ang) * r };
    this._play(a.birds, { category: 'ambience', owner: 'ambience', pos, ref: this.cfg.refDistance.bird, gain: a.birdGain, cutoff: airCutoff(r) });
  }

  // ------------------------------------------------------------------ occlusion

  /** Line of sight listener -> source through the static world (cached, budgeted). */
  _occlusion(pos) {
    const o = this.cfg.occlusion;
    const clear = { gain: 1, cutoff: 20000 };
    if (!o.enabled || !this.raycast) return clear;
    const L = this.listener;
    const k = `${Math.round(pos.x * 2)},${Math.round(pos.y * 2)},${Math.round(pos.z * 2)}|${Math.round(L.x * 2)},${Math.round(L.y * 2)},${Math.round(L.z * 2)}`;
    const cached = this._occCache.get(k);
    if (cached && this.simTime - cached.t <= o.cacheSeconds) return cached.v;
    if (this._raysThisTick >= o.raycastsPerTick) return cached ? cached.v : clear;
    this._raysThisTick++;
    this.stats.occlusionRaycasts++;
    const d = dist(pos, L);
    if (d < 0.3) return clear;
    this._rayO.x = L.x;
    this._rayO.y = L.y;
    this._rayO.z = L.z;
    this._rayD.x = (pos.x - L.x) / d;
    this._rayD.y = (pos.y - L.y) / d;
    this._rayD.z = (pos.z - L.z) / d;
    let hit = null;
    try {
      hit = this.raycast(this._rayO, this._rayD, d - 0.25);
    } catch {
      hit = null;
    }
    const v = hit ? { gain: o.gain, cutoff: o.cutoffHz } : clear;
    if (hit) this.stats.occluded++;
    if (this._occCache.size > 256) this._occCache.clear();
    this._occCache.set(k, { t: this.simTime, v });
    return v;
  }

  // ------------------------------------------------------------------ voices

  _rand(a, b) {
    return a + (b - a) * this.random();
  }

  _pick(key) {
    const list = this.bank.sounds[key];
    if (!list || list.length === 0) return null;
    if (list.length === 1) return list[0];
    const last = this.lastVariation.get(key);
    let i = Math.floor(this.random() * list.length) % list.length;
    if (list[i] === last) i = (i + 1 + Math.floor(this.random() * (list.length - 1))) % list.length;
    this.lastVariation.set(key, list[i]);
    return list[i];
  }

  _count(key, category, file = null, owner = null, extra = null) {
    this.stats.played++;
    this.stats.byKey[key] = (this.stats.byKey[key] || 0) + 1;
    this.stats.byCategory[category] = (this.stats.byCategory[category] || 0) + 1;
    this.log.push({ key, file, category, owner, t: this.ctx ? Number(this.ctx.currentTime.toFixed(3)) : 0, ...(extra || {}) });
    if (this.log.length > 60) this.log.shift();
  }

  /**
   * Plays one variation of `key`.
   * opts: { category, owner, pos (null = not spatial), ref, gain, delay, cutoff }
   */
  _play(key, opts) {
    if (!this.ctx || !this.enabled || !key) return null;
    const cat = this.cfg.categories[opts.category];
    const file = this._pick(key);
    const b = file ? this.buffers.get(file) : null;
    if (!b) {
      this.stats.skippedNoBuffer++;
      return null;
    }
    this._pruneEnded();
    this._enforceLimits(opts.category, opts.owner, opts.maxPerOwnerOverride);
    const c = this.ctx;
    const now = c.currentTime;
    const when = now + Math.max(0, opts.delay || 0);
    const src = c.createBufferSource();
    src.buffer = b.buffer;
    const rate = cat.pitchCents ? Math.pow(2, this._rand(-cat.pitchCents, cat.pitchCents) / 1200) : 1;
    src.playbackRate.value = rate;
    const g = c.createGain();
    g.gain.value = (opts.gain ?? 1) * (cat.gainDb ? dbToGain(this._rand(-cat.gainDb, cat.gainDb)) : 1);
    src.connect(g);
    let last = g;
    let filter = null;
    if (opts.cutoff && opts.cutoff < 19000) {
      filter = c.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.value = opts.cutoff;
      filter.Q.value = 0.707;
      last.connect(filter);
      last = filter;
    }
    let panner = null;
    if (opts.pos) {
      panner = c.createPanner();
      const far = this.cfg.hrtfMaxDistance && dist(opts.pos, this.listener) > this.cfg.hrtfMaxDistance;
      panner.panningModel = far ? 'equalpower' : this.cfg.panningModel;
      panner.distanceModel = 'inverse';
      panner.refDistance = opts.ref || 1;
      panner.maxDistance = 10000;
      panner.rolloffFactor = 1;
      setPos(panner, 'position', opts.pos);
      last.connect(panner);
      last = panner;
    }
    last.connect(this.buses[opts.category]);
    src.start(when, b.offset);
    const dur = (b.buffer.duration - b.offset) / rate;
    const v = { id: ++this._voiceSeq, key, file, category: opts.category, owner: opts.owner ?? null, src, gain: g, filter, panner, start: when, end: when + dur, loop: false };
    src.onended = () => this._removeVoice(v);
    this.voices.push(v);
    this._count(key, opts.category, file, v.owner, { spatial: !!opts.pos, delay: Number((when - now).toFixed(3)) });
    return v;
  }

  _enforceLimits(category, owner, perOwnerOverride) {
    const cat = this.cfg.categories[category];
    const inCat = this.voices.filter((v) => v.category === category && !v.loop);
    const maxOwner = perOwnerOverride ?? cat.maxPerOwner;
    if (owner != null && maxOwner) {
      const mine = inCat.filter((v) => v.owner === owner);
      while (mine.length >= maxOwner) {
        const v = mine.shift();
        this._stopVoice(v, this.cfg.stopFade);
        this.stats.stolen++;
        inCat.splice(inCat.indexOf(v), 1);
      }
    }
    while (inCat.length >= cat.maxVoices) {
      const v = inCat.shift();
      this._stopVoice(v, this.cfg.stopFade);
      this.stats.stolen++;
    }
  }

  _stopVoice(v, fade = this.cfg.stopFade) {
    if (v.stopped) return;
    v.stopped = true;
    const c = this.ctx;
    if (c) {
      const t = c.currentTime;
      try {
        v.gain.gain.cancelScheduledValues(t);
        v.gain.gain.setValueAtTime(v.gain.gain.value, t);
        v.gain.gain.setTargetAtTime(0, t, Math.max(0.001, fade / 3));
        // a voice scheduled for later is stopped before it starts (never heard)
        v.src.stop(v.start > t ? t : t + fade);
      } catch {
        /* already stopped */
      }
    }
    this._removeVoice(v);
  }

  _removeVoice(v) {
    const i = this.voices.indexOf(v);
    if (i >= 0) this.voices.splice(i, 1);
    if (v === this.wind) this.wind = null;
  }

  _pruneEnded() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    for (let i = this.voices.length - 1; i >= 0; i--) {
      const v = this.voices[i];
      if (!v.loop && v.end < t - 0.05) this.voices.splice(i, 1);
    }
  }

  /** Stops the sounds owned by combatant `id` (optionally only some categories). */
  stopOwner(id, categories = null) {
    const owner = this._ownerOf(id);
    for (const v of this.voices.slice()) {
      if (v.owner === owner && (!categories || categories.includes(v.category))) this._stopVoice(v);
    }
  }

  /** Stops every sound (pause, menus, death screen, round reset, new session). */
  stopAll(reason = '') {
    const n = this.voices.length;
    for (const v of this.voices.slice()) this._stopVoice(v, v.loop ? 0.25 : this.cfg.stopFade);
    this.wind = null;
    if (n) this.stats.stoppedByReset += n;
    this.lastStop = reason;
  }

  // ------------------------------------------------------------------ state

  /** Decoded buffers vs the bank: largest skipped lead-in and largest duration difference (seconds). */
  bufferCheck() {
    let maxLeadIn = 0;
    let maxDurationError = 0;
    for (const [f, b] of this.buffers) {
      maxLeadIn = Math.max(maxLeadIn, b.offset);
      const meta = this.bank.files[f];
      if (meta && b.buffer) maxDurationError = Math.max(maxDurationError, Math.abs(b.buffer.duration - b.offset - meta.duration));
    }
    return { maxLeadIn: Number(maxLeadIn.toFixed(4)), maxDurationError: Number(maxDurationError.toFixed(4)) };
  }

  getState() {
    this._pruneEnded();
    const active = {};
    for (const v of this.voices) active[v.category] = (active[v.category] || 0) + 1;
    return {
      unlocked: !!this.ctx,
      contextState: this.ctx ? this.ctx.state : 'none',
      masterGain: this.masterGain,
      files: this.files().length,
      fetched: this.stats.fetched,
      decoded: this.stats.decoded,
      buffers: this.buffers.size,
      playing: this.playing,
      ambience: !!this.wind,
      activeVoices: this.voices.length,
      activeByCategory: active,
      played: this.stats.played,
      byKey: { ...this.stats.byKey },
      byCategory: { ...this.stats.byCategory },
      // legacy summary names used by older tests / HUD debug
      byType: { ...this.stats.byKey },
      stats: { ...this.stats, byKey: undefined, byCategory: undefined },
      lastStop: this.lastStop || null,
      bufferCheck: this.bufferCheck(),
      log: this.log.slice(-20),
    };
  }
}

function defaultContextFactory() {
  const AC = typeof window !== 'undefined' ? window.AudioContext || window.webkitAudioContext : null;
  return AC ? new AC() : null;
}

function defaultFetch(url) {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
    return r.arrayBuffer();
  });
}
