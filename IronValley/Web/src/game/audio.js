// Event-driven game audio (WebAudio). All sounds are SHORT SYNTHESIZED PLACEHOLDERS (noise bursts,
// clicks, thumps) - not final assets. Every sound is a one-shot started by a real game event (shot, dry
// fire, reload commit, hit, footstep), so stopping fire, pausing, dying or restarting can never leave a
// looping sound behind. Spatialised with a PannerNode per sound (distance attenuation + direction) and
// the listener on the camera. The AudioContext is created on the first user gesture (autoplay policy);
// without it the system stays silent and does nothing.

export class GameAudio {
  constructor(settings) {
    this.settings = settings;
    this.ctx = null;
    this.master = null;
    this.noise = null;
    this.enabled = true;
    this.played = 0;
    this.byType = {};
    settings.onChange((key) => {
      if (key === 'masterVolume' || key === '*') this._applyVolume();
    });
  }

  /** Call from a user gesture (menu click). Safe to call repeatedly. */
  unlock() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
      return true;
    }
    const AC = typeof window !== 'undefined' ? window.AudioContext || window.webkitAudioContext : null;
    if (!AC) return false;
    try {
      this.ctx = new AC();
    } catch {
      this.ctx = null;
      return false;
    }
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this._applyVolume();
    const len = Math.floor(this.ctx.sampleRate * 0.5);
    this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    let s = 12345;
    for (let i = 0; i < len; i++) {
      s = (Math.imul(s, 1103515245) + 12345) >>> 0;
      d[i] = (s / 4294967296) * 2 - 1;
    }
    return true;
  }

  _applyVolume() {
    if (this.master) this.master.gain.value = this.settings.get('masterVolume');
  }

  get masterGain() {
    return this.master ? this.master.gain.value : this.settings.get('masterVolume');
  }

  /** Listener at the camera (position + forward/up vectors). */
  setListener(pos, forward, up) {
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

  _out(pos, refDistance = 4) {
    if (!pos) return this.master;
    const p = this.ctx.createPanner();
    p.panningModel = 'equalpower';
    p.distanceModel = 'inverse';
    p.refDistance = refDistance;
    p.maxDistance = 300;
    p.rolloffFactor = 1;
    if (p.positionX) {
      p.positionX.value = pos.x;
      p.positionY.value = pos.y;
      p.positionZ.value = pos.z;
    } else p.setPosition(pos.x, pos.y, pos.z);
    p.connect(this.master);
    return p;
  }

  _count(type) {
    this.played++;
    this.byType[type] = (this.byType[type] || 0) + 1;
  }

  _noiseBurst(out, { dur, freq, q = 0.8, gain, type = 'lowpass', attack = 0.002 }) {
    const c = this.ctx;
    const t = c.currentTime;
    const src = c.createBufferSource();
    src.buffer = this.noise;
    const f = c.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    f.Q.value = q;
    const g = c.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(gain, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(out);
    src.start(t);
    src.stop(t + dur + 0.02);
  }

  _tone(out, { dur, f0, f1, gain, type = 'sine' }) {
    const c = this.ctx;
    const t = c.currentTime;
    const o = c.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    const g = c.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  /** Shot: noise crack + low thump; pistol lighter. pos = muzzle (null = local player, not panned). */
  shot(pos, heavy = true) {
    if (!this.ctx || !this.enabled) return;
    this._count('shot');
    const out = this._out(pos, 6);
    this._noiseBurst(out, { dur: heavy ? 0.16 : 0.1, freq: heavy ? 2600 : 3400, gain: heavy ? 0.9 : 0.6 });
    this._tone(out, { dur: heavy ? 0.14 : 0.08, f0: heavy ? 110 : 160, f1: 40, gain: heavy ? 0.7 : 0.4 });
  }

  click(pos, kind = 'dry') {
    if (!this.ctx || !this.enabled) return;
    this._count(kind);
    const out = this._out(pos, 2);
    const f = kind === 'dry' ? 2400 : kind === 'bolt_release' ? 1500 : kind === 'mag_insert' ? 900 : 1900;
    this._noiseBurst(out, { dur: 0.035, freq: f, q: 4, gain: 0.35, type: 'bandpass', attack: 0.001 });
  }

  hit(pos, body = true) {
    if (!this.ctx || !this.enabled) return;
    this._count(body ? 'hit_body' : 'hit_world');
    const out = this._out(pos, 3);
    if (body) this._noiseBurst(out, { dur: 0.09, freq: 500, gain: 0.5 });
    else this._noiseBurst(out, { dur: 0.06, freq: 3200, q: 1.5, gain: 0.25, type: 'bandpass' });
  }

  hitmarker() {
    if (!this.ctx || !this.enabled) return;
    this._count('hitmarker');
    this._tone(this.master, { dur: 0.05, f0: 1800, f1: 1400, gain: 0.12, type: 'triangle' });
  }

  footstep(pos, surface = 'concrete', loudness = 0.5) {
    if (!this.ctx || !this.enabled) return;
    this._count('footstep');
    const out = this._out(pos, 2.5);
    const f = surface === 'metal' ? 2200 : surface === 'plaster' ? 1300 : 900;
    this._noiseBurst(out, { dur: 0.06, freq: f, q: 1.2, gain: 0.25 * loudness, type: 'bandpass' });
  }

  getState() {
    return { unlocked: !!this.ctx, contextState: this.ctx ? this.ctx.state : 'none', masterGain: this.masterGain, played: this.played, byType: { ...this.byType } };
  }
}
