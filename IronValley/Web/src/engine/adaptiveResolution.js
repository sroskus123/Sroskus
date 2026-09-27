// Adaptive internal resolution: lowers the render scale when frames are consistently slow and raises it again
// when there is headroom. Changes are rate limited to avoid oscillation.
//
// Fixes (optics playtest, "blurry when aiming"):
//  - The frame time is the requestAnimationFrame interval, which on a vsynced display never goes below the refresh
//    period. The old raise threshold (11.5 ms) is below a 60 Hz display's 16.7 ms, so on 60 Hz the scale could only
//    go DOWN and never came back: one slow stretch left the game at 0.9 / 0.8 ... 0.5 for the rest of the session.
//    Now "headroom" = the frames hit the measured refresh period (the smallest recent intervals).
//  - Single hitches (tab switch, a shader compile, GC) no longer count (intervals > spikeMs are ignored).
//  - A scale that failed is retried only after a cooldown that doubles each time (no pumping between two scales).
//  - hold (while aiming) freezes the scale: no visible resolution step in the sight picture.

export class AdaptiveResolution {
  constructor({ min = 0.5, max = 1, targetMs = 16.9, raiseMs = 11.5, interval = 1.5, spikeMs = 120, raiseChecks = 2, retryS = 8 } = {}) {
    this.min = min;
    this.max = max;
    this.targetMs = targetMs;
    this.raiseMs = raiseMs;
    this.interval = interval;
    this.spikeMs = spikeMs;
    this.raiseChecks = raiseChecks;
    this.retryS = retryS;
    this.scale = max;
    this.ema = targetMs;
    this.timer = 0;
    this.changes = 0;
    this.refreshMs = null; // estimated display refresh period (smallest recent frame intervals)
    this.good = 0; // consecutive checks with headroom
    this.time = 0;
    this.failed = new Map(); // scale -> { until, backoff }
    this.held = false;
  }

  /** Frame time with headroom: at the display's refresh period (vsync) or clearly faster than the target. */
  get raiseThresholdMs() {
    const vs = this.refreshMs ? this.refreshMs * 1.06 : 0;
    return Math.max(this.raiseMs, Math.min(vs, this.targetMs * 1.05));
  }

  /**
   * @param {number} frameMs  interval since the previous frame (ms)
   * @param {number} dt       seconds (for the rate limit)
   * @param {object} [o]      { hold: freeze the scale now (aiming) }
   * @returns {number|null} new scale if it changed
   */
  update(frameMs, dt, { hold = false } = {}) {
    if (!Number.isFinite(frameMs) || frameMs <= 0) return null;
    this.time += Math.max(0, dt);
    if (frameMs > this.spikeMs) return null; // hitch, not load
    // refresh period: follows the smallest intervals (drops at once, rises very slowly)
    this.refreshMs = this.refreshMs === null ? frameMs : Math.min(frameMs, this.refreshMs + (frameMs - this.refreshMs) * 0.002);
    this.ema += (frameMs - this.ema) * 0.08;
    this.held = !!hold;
    if (hold) {
      this.timer = 0;
      this.good = 0;
      return null;
    }
    this.timer += dt;
    if (this.timer < this.interval) return null;
    this.timer = 0;
    let next = this.scale;
    if (this.ema > this.targetMs * 1.12 && this.scale > this.min) {
      next = Math.max(this.min, this.scale - 0.1);
      this.good = 0;
      // the scale we leave failed: retry it only after a cooldown (doubling)
      const key = Math.round(this.scale * 100);
      const f = this.failed.get(key);
      const backoff = f ? Math.min(f.backoff * 2, 120) : this.retryS;
      this.failed.set(key, { until: this.time + backoff, backoff });
    } else if (this.ema <= this.raiseThresholdMs && this.scale < this.max) {
      this.good++;
      const cand = Math.min(this.max, this.scale + 0.05);
      const f = this.failed.get(Math.round(cand * 100));
      if (this.good >= this.raiseChecks && (!f || this.time >= f.until)) {
        next = cand;
        this.good = 0;
      }
    } else this.good = 0;
    if (Math.abs(next - this.scale) < 1e-3) return null;
    this.scale = Math.round(next * 100) / 100;
    this.changes++;
    return this.scale;
  }

  reset(scale = this.max) {
    this.scale = scale;
    this.timer = 0;
    this.good = 0;
  }
}
