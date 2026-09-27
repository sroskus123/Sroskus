// AI debugging: window.__IV.ai (tests / debugging only; the game never depends on it) and an optional
// 3D overlay (paths, last known positions, reserved cover, view direction, blocked navmesh areas).
//
//   __IV.ai.getDebug()            full snapshot (per bot: task, target, perception, memory, path, cover,
//                                 reaction timer, fire state, stuck events) + system metrics
//   __IV.ai.bot(id)               snapshot of one bot
//   __IV.ai.setOverlay(on)        3D overlay in the game scene (needs __IV._game.scene)
//   __IV.ai.setEnabled(on)        stop / resume AI updates (session.aiEnabled)

import { BufferGeometry, Float32BufferAttribute, Group, LineBasicMaterial, LineSegments, Mesh, MeshBasicMaterial, SphereGeometry } from 'three';

const TEAM_COLORS = [0x3d8bfd, 0xe5533d, 0xf2c230];

export function installAIDebugApi(api, sys) {
  if (typeof window === 'undefined') return;
  const iv = window.__IV;
  if (!iv || (iv.ai && iv.ai._owner === api)) return;
  const autoOverlay = !!(sys.cfg.debug && sys.cfg.debug.overlay);
  iv.ai = {
    _owner: api,
    getDebug: () => api.getDebug(),
    bot: (id) => {
      const b = sys.byId.get(id);
      return b ? b.snapshot(sys.time) : null;
    },
    setOverlay: (on) => {
      if (on && !sys.overlay) {
        const scene = iv._game && iv._game.scene;
        if (!scene) return false;
        sys.overlay = new AIDebugOverlay(scene);
        sys.overlay.update(sys);
      } else if (!on && sys.overlay) {
        sys.overlay.dispose();
        sys.overlay = null;
      }
      return !!sys.overlay;
    },
    setEnabled: (on) => {
      const s = iv._game && iv._game.session;
      if (s) s.aiEnabled = !!on;
      return s ? s.aiEnabled : null;
    },
    /** Memory entries of one bot (last known positions, confidence, source). */
    memory: (id) => {
      const b = sys.byId.get(id);
      return b ? b.memory.snapshot(sys.time) : null;
    },
    /** Small per-bot state for per-tick checks. */
    brief: (id) => {
      const b = sys.byId.get(id);
      if (!b) return null;
      return {
        id,
        team: b.c.team,
        alive: b.c.alive,
        task: b.task,
        targetId: b.targetId,
        targetTeam: b.targetId && sys.combatants.get(b.targetId) ? sys.combatants.get(b.targetId).team : null,
        yaw: b.c.yaw,
        pos: [b.c.position.x, b.c.position.y, b.c.position.z],
        fireCmd: !!b.cmd.fire,
        fireBlocked: b.fireBlockedReason,
        weaponState: b._weapon() ? b._weapon().state.state : null,
        shots: b.metrics.shots,
        shotsDuringReload: b.metrics.shotsDuringReload,
        search: b.search ? { pos: b.search.pos.toArray() } : null,
        scripted: b.scripted ? { arrivedAt: b.scripted.arrivedAt } : null,
      };
    },
    /** All bots at once: [id, team, alive, x, y, z, task, targetTeam]. */
    positions: () =>
      sys.bots.map((b) => {
        const tt = b.targetId && sys.combatants.get(b.targetId) ? sys.combatants.get(b.targetId).team : null;
        return [b.c.id, b.c.team, b.c.alive, b.c.position.x, b.c.position.y, b.c.position.z, b.task, tt, b.metrics.shotsDuringReload];
      }),
    time: () => sys.time,
    navDebug: () => (sys.nav ? sys.nav.getDebug() : null),
    commandMove: (id, pos, opts) => api.commandMove(id, pos, opts),
    clearCommand: (id) => api.clearCommand(id),
    setGuardMode: (on) => api.setGuardMode(on),
    setLookHint: (id, yawDeg, seconds) => api.setLookHint(id, yawDeg, seconds),
    coverPoints: () => (sys.cover ? sys.cover.points.map((p) => ({ id: p.id, pos: p.pos.toArray(), normal: p.normal.toArray(), height: p.height, peek: p.peek })) : []),
  };
  // ai.json debug.overlay: start with the overlay on (debug builds / tuning sessions)
  if (autoOverlay) iv.ai.setOverlay(true);
}

/** Line / marker overlay, rebuilt from the AI state a few times per second (cheap, debug only). */
export class AIDebugOverlay {
  constructor(scene) {
    this.scene = scene;
    this.group = new Group();
    this.group.name = 'ai_debug_overlay';
    this.group.renderOrder = 999;
    scene.add(this.group);
    this.lineMat = new LineBasicMaterial({ vertexColors: true, depthTest: false, transparent: true, opacity: 0.9 });
    this.lines = new LineSegments(new BufferGeometry(), this.lineMat);
    this.lines.frustumCulled = false;
    this.group.add(this.lines);
    this.markerGeo = new SphereGeometry(0.18, 8, 6);
    this.markers = [];
  }

  update(sys) {
    const pos = [];
    const col = [];
    const seg = (a, b, color) => {
      pos.push(a.x, a.y, a.z, b.x, b.y, b.z);
      const r = ((color >> 16) & 255) / 255;
      const g = ((color >> 8) & 255) / 255;
      const bl = (color & 255) / 255;
      col.push(r, g, bl, r, g, bl);
    };
    const markers = [];
    for (const b of sys.bots) {
      if (!b.c.alive) continue;
      const color = TEAM_COLORS[b.c.team] || 0xffffff;
      const p = b.c.position;
      // path
      let prev = { x: p.x, y: p.y + 0.1, z: p.z };
      for (let i = b.move.index; i < b.move.path.length; i++) {
        const w = b.move.path[i];
        const q = { x: w.x, y: w.y + 0.1, z: w.z };
        seg(prev, q, color);
        prev = q;
      }
      // view direction (1.5 m)
      const eyeY = p.y + b.c.controller.eyeHeight;
      const f = { x: p.x - Math.sin(b.c.yaw) * 1.5, y: eyeY + Math.sin(b.c.pitch) * 1.5, z: p.z - Math.cos(b.c.yaw) * 1.5 };
      seg({ x: p.x, y: eyeY, z: p.z }, f, 0xffffff);
      // memory: line to each last known position (green = seen, yellow = heard / older)
      for (const e of b.memory.entries.values()) {
        if (e.conf < 0.3 && !e.seen) continue;
        seg({ x: p.x, y: eyeY, z: p.z }, { x: e.pos.x, y: e.pos.y + 1.0, z: e.pos.z }, e.seen ? 0x33ff66 : 0xffcc33);
        markers.push({ x: e.pos.x, y: e.pos.y + 1.0, z: e.pos.z, color: e.seen ? 0x33ff66 : 0xffcc33 });
      }
      // reserved cover
      if (b.cover) {
        const c = b.cover.pos;
        seg({ x: c.x, y: c.y, z: c.z }, { x: c.x, y: c.y + 1.2, z: c.z }, 0x00ffff);
        seg({ x: c.x, y: c.y + 0.3, z: c.z }, { x: c.x + b.cover.normal.x * 0.6, y: c.y + 0.3, z: c.z + b.cover.normal.z * 0.6 }, 0x00ffff);
      }
    }
    // blocked navmesh areas
    if (sys.nav) {
      for (const bl of sys.nav.blocks) {
        const c = bl.center;
        const n = 16;
        for (let i = 0; i < n; i++) {
          const a0 = (i / n) * Math.PI * 2;
          const a1 = ((i + 1) / n) * Math.PI * 2;
          seg({ x: c.x + Math.cos(a0) * bl.radius, y: c.y + 0.15, z: c.z + Math.sin(a0) * bl.radius }, { x: c.x + Math.cos(a1) * bl.radius, y: c.y + 0.15, z: c.z + Math.sin(a1) * bl.radius }, 0xff00ff);
        }
      }
    }
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new Float32BufferAttribute(col, 3));
    this.lines.geometry.dispose();
    this.lines.geometry = g;
    // markers (pooled)
    while (this.markers.length < markers.length) {
      const m = new Mesh(this.markerGeo, new MeshBasicMaterial({ color: 0xffffff, depthTest: false, transparent: true, opacity: 0.8 }));
      m.renderOrder = 999;
      this.group.add(m);
      this.markers.push(m);
    }
    this.markers.forEach((m, i) => {
      const k = markers[i];
      m.visible = !!k;
      if (k) {
        m.position.set(k.x, k.y, k.z);
        m.material.color.setHex(k.color);
      }
    });
  }

  dispose() {
    this.scene.remove(this.group);
    this.lines.geometry.dispose();
    this.lineMat.dispose();
    this.markerGeo.dispose();
    for (const m of this.markers) m.material.dispose();
  }
}
