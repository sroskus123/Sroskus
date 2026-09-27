// Fixed-step simulation loop with render interpolation.
//
// The simulation always advances in ticks of exactly `fixedDt` (1/60 s by default).
// Real frame time is fed into an accumulator; the loop runs as many whole ticks as fit
// and hands the remaining fraction (alpha) to the renderer for interpolation.
//
// To keep the number of ticks exact regardless of frame pacing (30 / 60 / 144 FPS must
// produce identical simulations), elapsed simulated time is tracked as an absolute sum and
// the tick count is derived from it with a tiny epsilon, instead of repeatedly subtracting
// fixedDt from a float accumulator (which drifts).

const EPS_TICKS = 1e-6;

export class FixedStepLoop {
  /**
   * @param {object} opts
   * @param {(dt:number, tick:number)=>void} opts.step  one simulation tick
   * @param {(alpha:number, frameDt:number)=>void} opts.render  draw one frame
   * @param {number} [opts.fixedDt]
   * @param {number} [opts.maxFrameDt]  larger real gaps are clamped (tab switch, debugger)
   * @param {number} [opts.maxTicksPerFrame]
   */
  constructor({ step, render, fixedDt = 1 / 60, maxFrameDt = 0.25, maxTicksPerFrame = 20 }) {
    this.stepFn = step;
    this.renderFn = render;
    this.fixedDt = fixedDt;
    this.maxFrameDt = maxFrameDt;
    this.maxTicksPerFrame = maxTicksPerFrame;
    this.timeScale = 1;

    this.simTime = 0; // total simulated time fed into the accumulator (seconds)
    this.ticks = 0; // ticks executed
    this.alpha = 0;
    this.frames = 0;
    this.clampedFrames = 0;

    this.running = false;
    this.frozen = false; // when true the real-time driver does nothing (test control)
    this.renderEnabled = true;
    this._lastTs = null;
    this._rafId = 0;
    this._boundRaf = (ts) => this._onRaf(ts);

    // frame time statistics (real time between rAF callbacks)
    this.fps = 0;
    this._fpsAccum = 0;
    this._fpsFrames = 0;
    this.lastFrameMs = 0;
  }

  /** Advance by one frame of `realDt` seconds (clamped and scaled). Returns ticks run. */
  frame(realDt, { render = this.renderEnabled } = {}) {
    let dt = Number.isFinite(realDt) && realDt > 0 ? realDt : 0;
    if (dt > this.maxFrameDt) {
      dt = this.maxFrameDt;
      this.clampedFrames++;
    }
    dt *= this.timeScale;
    this.simTime += dt;

    const targetTicks = Math.floor(this.simTime / this.fixedDt + EPS_TICKS);
    let toRun = targetTicks - this.ticks;
    if (toRun > this.maxTicksPerFrame) {
      // Spiral-of-death guard: drop the backlog instead of freezing the page.
      toRun = this.maxTicksPerFrame;
      this.simTime = (this.ticks + toRun) * this.fixedDt;
    }
    for (let i = 0; i < toRun; i++) {
      this.stepFn(this.fixedDt, this.ticks);
      this.ticks++;
    }
    this.alpha = Math.min(Math.max(this.simTime / this.fixedDt - this.ticks, 0), 1);
    this.frames++;
    if (render) this.renderFn(this.alpha, dt);
    return toRun;
  }

  /** Run exactly n ticks synchronously (test helper); does not touch the time accumulator phase. */
  stepTicks(n, { render = false } = {}) {
    for (let i = 0; i < n; i++) {
      this.stepFn(this.fixedDt, this.ticks);
      this.ticks++;
      this.simTime += this.fixedDt;
    }
    this.alpha = Math.min(Math.max(this.simTime / this.fixedDt - this.ticks, 0), 1);
    if (render) this.renderFn(this.alpha, 0);
  }

  /** Drop any fractional accumulated time (so the next frame starts on a tick boundary). */
  resetAccumulator() {
    this.simTime = this.ticks * this.fixedDt;
    this.alpha = 0;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this._lastTs = null;
    this._rafId = requestAnimationFrame(this._boundRaf);
  }

  stop() {
    this.running = false;
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = 0;
  }

  _onRaf(ts) {
    if (!this.running) return;
    this._rafId = requestAnimationFrame(this._boundRaf);
    const last = this._lastTs;
    this._lastTs = ts;
    if (last === null) return;
    const realDt = (ts - last) / 1000;
    this.lastFrameMs = ts - last;
    this._fpsAccum += realDt;
    this._fpsFrames++;
    if (this._fpsAccum >= 0.5) {
      this.fps = this._fpsFrames / this._fpsAccum;
      this._fpsAccum = 0;
      this._fpsFrames = 0;
    }
    if (this.frozen) return;
    this.frame(realDt);
  }
}
