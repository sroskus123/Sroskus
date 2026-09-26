// Adaptive internal resolution: lowers the render scale when frames are consistently slow and
// raises it again when there is headroom. Changes are rate limited to avoid oscillation.

export class AdaptiveResolution {
  constructor({ min = 0.5, max = 1, targetMs = 16.9, raiseMs = 11.5, interval = 1.5 } = {}) {
    this.min = min;
    this.max = max;
    this.targetMs = targetMs;
    this.raiseMs = raiseMs;
    this.interval = interval;
    this.scale = max;
    this.ema = targetMs;
    this.timer = 0;
    this.changes = 0;
  }

  /** @returns {number|null} new scale if it changed */
  update(frameMs, dt) {
    if (!Number.isFinite(frameMs) || frameMs <= 0 || frameMs > 1000) return null;
    this.ema += (frameMs - this.ema) * 0.08;
    this.timer += dt;
    if (this.timer < this.interval) return null;
    this.timer = 0;
    let next = this.scale;
    if (this.ema > this.targetMs * 1.12 && this.scale > this.min) next = Math.max(this.min, this.scale - 0.1);
    else if (this.ema < this.raiseMs && this.scale < this.max) next = Math.min(this.max, this.scale + 0.05);
    if (Math.abs(next - this.scale) < 1e-3) return null;
    this.scale = Math.round(next * 100) / 100;
    this.changes++;
    return this.scale;
  }

  reset(scale = this.max) {
    this.scale = scale;
    this.timer = 0;
  }
}
