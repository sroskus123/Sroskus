// WebGL2 renderer setup: sRGB output, ACES filmic tone mapping, physically based lighting,
// soft PCF shadows, and an adjustable internal resolution scale.

import { ACESFilmicToneMapping, PCFShadowMap, SRGBColorSpace, WebGLRenderer } from 'three';

export function isWebGL2Available() {
  try {
    const c = document.createElement('canvas');
    return !!c.getContext('webgl2');
  } catch {
    return false;
  }
}

export class Renderer {
  /**
   * @param {HTMLElement} container
   * @param {{exposure:number}} opts
   */
  constructor(container, { exposure = 1 } = {}) {
    this.container = container;
    const canvas = document.createElement('canvas');
    canvas.className = 'iv-canvas';
    canvas.setAttribute('tabindex', '0');
    canvas.setAttribute('aria-label', 'Herní pohled');
    const attributes = {
      alpha: false,
      antialias: true,
      depth: true,
      stencil: false,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false,
    };
    const gl = canvas.getContext('webgl2', attributes);
    if (!gl) throw new Error('WebGL2 není v tomto prohlížeči dostupné.');
    this.renderer = new WebGLRenderer({ canvas, context: gl, ...attributes });
    const r = this.renderer;
    r.outputColorSpace = SRGBColorSpace;
    r.toneMapping = ACESFilmicToneMapping;
    r.toneMappingExposure = exposure;
    r.shadowMap.enabled = true;
    r.shadowMap.type = PCFShadowMap; // soft via light.shadow.radius (Vogel disk + hardware PCF)
    r.autoClear = false;
    container.appendChild(canvas);
    this.canvas = canvas;
    this.scale = 1;
    this.maxPixelRatio = 2;
    this.width = 1;
    this.height = 1;
    this.contextLost = false;
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      this.contextLost = true;
    });
    canvas.addEventListener('webglcontextrestored', () => {
      this.contextLost = false;
    });
    this.resize();
  }

  get pixelRatio() {
    return Math.min(window.devicePixelRatio || 1, this.maxPixelRatio) * this.scale;
  }

  setScale(scale) {
    const s = Math.min(Math.max(scale, 0.25), 1);
    if (Math.abs(s - this.scale) < 1e-3) return false;
    this.scale = s;
    this.renderer.setPixelRatio(this.pixelRatio);
    this.renderer.setSize(this.width, this.height, false);
    return true;
  }

  /** Returns true if the size changed. */
  resize() {
    const w = Math.max(1, this.container.clientWidth || window.innerWidth);
    const h = Math.max(1, this.container.clientHeight || window.innerHeight);
    if (w === this.width && h === this.height) return false;
    this.width = w;
    this.height = h;
    this.renderer.setPixelRatio(this.pixelRatio);
    this.renderer.setSize(w, h, false);
    return true;
  }

  get aspect() {
    return this.width / this.height;
  }

  getInfo() {
    const gl = this.renderer.getContext();
    let gpu = 'unknown';
    try {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      if (ext) gpu = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
    } catch {
      /* ignore */
    }
    return {
      webgl2: typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext,
      gpu,
      width: this.width,
      height: this.height,
      pixelRatio: this.pixelRatio,
      scale: this.scale,
      drawingBuffer: [gl.drawingBufferWidth, gl.drawingBufferHeight],
      calls: this.renderer.info.render.calls,
      triangles: this.renderer.info.render.triangles,
      programs: this.renderer.info.programs ? this.renderer.info.programs.length : 0,
    };
  }
}
