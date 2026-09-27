// Minimal fake WebAudio context for unit tests of src/audio/audioSystem.js. Records every node, started
// source (with its buffer, start time, offset, stop time) and connection, with a manually advanced clock.

class FakeParam {
  constructor(v = 0) {
    this.value = v;
    this.events = [];
  }
  setValueAtTime(v, t) {
    this.events.push(['set', v, t]);
    this.value = v;
    return this;
  }
  setTargetAtTime(v, t, tau) {
    this.events.push(['target', v, t, tau]);
    return this;
  }
  linearRampToValueAtTime(v, t) {
    this.events.push(['linear', v, t]);
    return this;
  }
  exponentialRampToValueAtTime(v, t) {
    this.events.push(['exp', v, t]);
    return this;
  }
  cancelScheduledValues(t) {
    this.events.push(['cancel', t]);
    return this;
  }
}

class FakeNode {
  constructor(ctx, kind) {
    this.ctx = ctx;
    this.kind = kind; // node class (the real `type` property of biquads / oscillators is left to the code under test)
    this.outputs = [];
    ctx.nodes.push(this);
  }
  connect(n) {
    this.outputs.push(n);
    return n;
  }
  disconnect() {
    this.outputs = [];
  }
}

class FakeSource extends FakeNode {
  constructor(ctx) {
    super(ctx, 'source');
    this.buffer = null;
    this.playbackRate = new FakeParam(1);
    this.loop = false;
    this.loopStart = 0;
    this.loopEnd = 0;
    this.startedAt = null;
    this.offset = 0;
    this.stoppedAt = null;
    this.onended = null;
  }
  start(when = 0, offset = 0) {
    if (this.startedAt !== null) throw new Error('start twice');
    this.startedAt = when;
    this.offset = offset;
    this.ctx.started.push(this);
  }
  stop(when = 0) {
    this.stoppedAt = when;
  }
  /** True if the source is audible at time t (started, not yet stopped, inside its buffer). */
  audibleAt(t) {
    if (this.startedAt === null || t < this.startedAt) return false;
    if (this.stoppedAt !== null && t >= this.stoppedAt) return false;
    if (this.loop) return true;
    return t < this.startedAt + (this.buffer.duration - this.offset) / this.playbackRate.value;
  }
}

export class FakeAudioBuffer {
  constructor({ duration = 0.5, sampleRate = 44100, channels = 1, leadIn = 0 } = {}) {
    this.duration = duration;
    this.sampleRate = sampleRate;
    this.numberOfChannels = channels;
    this.length = Math.round(duration * sampleRate);
    this._data = new Float32Array(this.length);
    const i0 = Math.round(leadIn * sampleRate);
    for (let i = i0; i < this.length; i++) this._data[i] = 0.5 * Math.exp(-(i - i0) / (0.05 * sampleRate));
  }
  getChannelData() {
    return this._data;
  }
}

export class FakeAudioContext {
  constructor({ state = 'running' } = {}) {
    this.currentTime = 0;
    this.sampleRate = 44100;
    this.state = state;
    this.nodes = [];
    this.started = [];
    this.destination = new FakeNode(this, 'destination');
    this.listener = {
      positionX: new FakeParam(),
      positionY: new FakeParam(),
      positionZ: new FakeParam(),
      forwardX: new FakeParam(),
      forwardY: new FakeParam(),
      forwardZ: new FakeParam(-1),
      upX: new FakeParam(),
      upY: new FakeParam(1),
      upZ: new FakeParam(),
    };
    this.decodeCalls = 0;
  }
  resume() {
    this.state = 'running';
    return Promise.resolve();
  }
  createGain() {
    const n = new FakeNode(this, 'gain');
    n.gain = new FakeParam(1);
    return n;
  }
  createBufferSource() {
    return new FakeSource(this);
  }
  createBiquadFilter() {
    const n = new FakeNode(this, 'biquad');
    n.frequency = new FakeParam(350);
    n.Q = new FakeParam(1);
    return n;
  }
  createPanner() {
    const n = new FakeNode(this, 'panner');
    n.positionX = new FakeParam();
    n.positionY = new FakeParam();
    n.positionZ = new FakeParam();
    return n;
  }
  createDynamicsCompressor() {
    const n = new FakeNode(this, 'compressor');
    for (const k of ['threshold', 'knee', 'ratio', 'attack', 'release']) n[k] = new FakeParam();
    return n;
  }
  createWaveShaper() {
    return new FakeNode(this, 'waveshaper');
  }
  createOscillator() {
    const n = new FakeSource(this);
    n.kind = 'oscillator';
    n.frequency = new FakeParam(440);
    n.buffer = { duration: 1 };
    return n;
  }
  decodeAudioData(ab) {
    this.decodeCalls++;
    const meta = ab && ab.meta ? ab.meta : {};
    return Promise.resolve(new FakeAudioBuffer(meta));
  }
  advance(dt) {
    this.currentTime += dt;
  }
  /** Sources audible now (buffer sources only). */
  audible(t = this.currentTime) {
    return this.started.filter((s) => s.kind === 'source' && s.audibleAt(t));
  }
}

/** Fake encoded file: decodeAudioData returns a FakeAudioBuffer with this metadata. */
export function fakeEncoded(meta) {
  return { meta, slice() { return this; } };
}
