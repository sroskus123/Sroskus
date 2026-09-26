// In-game HUD (DOM overlay, Czech texts). Shows only real game state handed in by the game each
// frame: health (Match), ammo with chamber (core weapon), weapon + optic, active zone (name, distance,
// direction, control state, progress), team scores, round timer, ally markers, hit marker, damage
// direction, reload progress, death / respawn countdown and a short kill feed. Menus: menus.js.

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

function setText(e, t) {
  const s = String(t);
  if (e.textContent !== s) e.textContent = s;
}

export function formatClock(seconds) {
  const s = Math.max(0, Math.ceil(seconds - 1e-9));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

export class Hud {
  /**
   * @param {HTMLElement} root
   * @param {object} o { levelName, teamsData }
   */
  constructor(root, { levelName = '', teamsData = null } = {}) {
    this.root = root;
    this.teamsData = teamsData;
    this.hud = el('div', 'iv-hud');
    this.hud.setAttribute('aria-hidden', 'true');

    // location (level name + tag)
    this.location = el('div', 'iv-location');
    this.locationName = el('span', 'iv-location-name', levelName);
    this.locationTag = el('span', 'iv-location-tag', 'vývojová mapa');
    this.location.append(this.locationName, this.locationTag);

    // top centre: timer, team scores, zone
    this.top = el('div', 'iv-top');
    this.timer = el('div', 'iv-timer', '');
    this.scores = el('div', 'iv-scores');
    this.teamEls = [];
    for (let t = 0; t < 3; t++) {
      const box = el('div', 'iv-team');
      const name = el('span', 'iv-team-name', '');
      const score = el('span', 'iv-team-score', '0');
      const bar = el('div', 'iv-team-bar');
      const fill = el('i');
      bar.append(fill);
      box.append(name, score, bar);
      this.scores.append(box);
      this.teamEls.push({ box, name, score, fill });
    }
    this.zone = el('div', 'iv-zone');
    this.zoneArrow = el('span', 'iv-zone-arrow', '▲');
    this.zoneName = el('span', 'iv-zone-name', '');
    this.zoneDist = el('span', 'iv-zone-dist', '');
    this.zoneState = el('span', 'iv-zone-state', '');
    this.zoneBar = el('div', 'iv-zone-bar');
    this.zoneFill = el('i');
    this.zoneBar.append(this.zoneFill);
    const zoneLine = el('div', 'iv-zone-line');
    zoneLine.append(this.zoneArrow, this.zoneName, this.zoneDist);
    this.zone.append(zoneLine, this.zoneState, this.zoneBar);
    this.top.append(this.timer, this.scores, this.zone);

    // kill feed (top right)
    this.killFeed = el('div', 'iv-killfeed');
    this._killKey = '';

    // crosshair, hit marker, damage direction
    this.crosshair = el('div', 'iv-crosshair');
    for (const c of ['t', 'b', 'l', 'r', 'dot']) this.crosshair.append(el('i', `iv-ch-${c}`));
    this.hitmarker = el('div', 'iv-hitmarker');
    this.dmgRing = el('div', 'iv-dmg');
    this.dmgArcs = [];
    this.vignette = el('div', 'iv-vignette');

    // health (bottom left)
    this.healthBox = el('div', 'iv-health');
    this.healthLabel = el('span', 'iv-health-label', 'ZDRAVÍ');
    this.healthNum = el('span', 'iv-health-num', '100');
    this.healthBar = el('div', 'iv-health-bar');
    this.healthFill = el('i');
    this.healthBar.append(this.healthFill);
    const hl = el('div', 'iv-health-line');
    hl.append(this.healthLabel, this.healthNum);
    this.healthBox.append(hl, this.healthBar);
    this.stance = el('div', 'iv-stance', '');

    // ammo (bottom right)
    this.ammoBox = el('div', 'iv-ammo');
    this.weaponName = el('div', 'iv-weapon-name', '');
    this.ammoMag = el('span', 'iv-ammo-mag', '');
    this.ammoChamber = el('span', 'iv-ammo-chamber', '+1');
    this.ammoChamber.title = 'náboj v komoře';
    this.ammoReserve = el('span', 'iv-ammo-res', '');
    this.fireMode = el('div', 'iv-fire-mode', '');
    const ammoLine = el('div', 'iv-ammo-line');
    ammoLine.append(this.ammoMag, this.ammoChamber, this.ammoReserve);
    this.reloadBar = el('div', 'iv-reload');
    this.reloadFill = el('i');
    this.reloadBar.append(this.reloadFill);
    this.reloadText = el('div', 'iv-reload-text', '');
    this.ammoBox.append(this.weaponName, ammoLine, this.fireMode, this.reloadText, this.reloadBar);

    // allies, notices, death overlay, banner
    this.allies = el('div', 'iv-allies');
    this.allyEls = new Map();
    this.notice = el('div', 'iv-notice', '');
    this.banner = el('div', 'iv-banner', '');
    this.death = el('div', 'iv-death');
    this.deathTitle = el('div', 'iv-death-title', 'Padl jsi');
    this.deathKiller = el('div', 'iv-death-killer', '');
    this.deathCount = el('div', 'iv-death-count', '');
    this.death.append(this.deathTitle, this.deathKiller, this.deathCount);
    this.fps = el('div', 'iv-fps', '');
    this.placeholderNote = el('div', 'iv-placeholder-note', '');

    this.hud.append(
      this.vignette,
      this.location,
      this.top,
      this.killFeed,
      this.allies,
      this.crosshair,
      this.hitmarker,
      this.dmgRing,
      this.healthBox,
      this.stance,
      this.ammoBox,
      this.notice,
      this.banner,
      this.death,
      this.fps,
      this.placeholderNote,
    );

    // touch / narrow note
    this.touchNote = el('div', 'iv-touch-note');
    this.touchNote.append(
      el('strong', '', 'Hra vyžaduje klávesnici a myš.'),
      el('span', '', ' Na dotykovém nebo příliš úzkém displeji ji nelze ovládat. Otevři ji na počítači (šířka okna alespoň 960 px).'),
    );
    root.append(this.hud, this.touchNote);
    this.noticeTimer = 0;
    this.hitTimer = 0;
    this.bannerTimer = 0;
    this.vignetteTimer = 0;
    this._updateTouchNote();
    window.addEventListener('resize', () => this._updateTouchNote());
    this.setMode('start');
  }

  _updateTouchNote() {
    const narrow = window.innerWidth < 900;
    let touchOnly = false;
    try {
      touchOnly = window.matchMedia('(pointer: coarse)').matches && !window.matchMedia('(any-pointer: fine)').matches;
    } catch {
      touchOnly = false;
    }
    this.touchNote.classList.toggle('iv-show', narrow || touchOnly);
  }

  setLevelName(name) {
    setText(this.locationName, name);
  }

  setLevelTag(tag) {
    setText(this.locationTag, tag);
  }

  setMode(mode) {
    this.mode = mode;
    this.hud.classList.toggle('iv-open', mode === 'playing' || mode === 'paused');
  }

  showNotice(text, seconds = 2.5) {
    this.notice.textContent = text;
    this.notice.classList.add('iv-show');
    this.noticeTimer = seconds;
  }

  showBanner(text, seconds = 2.5) {
    this.banner.textContent = text;
    this.banner.classList.add('iv-show');
    this.bannerTimer = seconds;
  }

  showHitmarker(kill = false, seconds = 0.14) {
    this.hitmarker.classList.add('iv-show');
    this.hitmarker.classList.toggle('iv-kill', kill);
    this.hitTimer = seconds;
  }

  /** Damage from a direction: angle (rad) relative to the view, 0 = front, + = left. */
  showDamage(angle, seconds = 1.6) {
    let arc = this.dmgArcs.find((a) => a.t <= 0);
    if (!arc) {
      if (this.dmgArcs.length >= 4) arc = this.dmgArcs.reduce((a, b) => (a.t < b.t ? a : b));
      else {
        arc = { e: el('i', 'iv-dmg-arc'), t: 0, dur: seconds };
        this.dmgRing.append(arc.e);
        this.dmgArcs.push(arc);
      }
    }
    arc.t = seconds;
    arc.dur = seconds;
    arc.angle = angle;
    arc.e.style.transform = `rotate(${(-angle * 180) / Math.PI}deg)`;
    arc.e.style.opacity = '1';
    this.vignetteTimer = 0.35;
  }

  setPlaceholderNote(text) {
    this.placeholderNote.textContent = text || '';
  }

  /** Timers advance with game time (fixed tick), so they pause with the game. */
  tick(dt) {
    if (this.noticeTimer > 0) {
      this.noticeTimer -= dt;
      if (this.noticeTimer <= 0) this.notice.classList.remove('iv-show');
    }
    if (this.hitTimer > 0) {
      this.hitTimer -= dt;
      if (this.hitTimer <= 0) this.hitmarker.classList.remove('iv-show');
    }
    if (this.bannerTimer > 0) {
      this.bannerTimer -= dt;
      if (this.bannerTimer <= 0) this.banner.classList.remove('iv-show');
    }
    for (const a of this.dmgArcs) {
      if (a.t > 0) {
        a.t -= dt;
        a.e.style.opacity = String(Math.max(0, a.t / a.dur));
      }
    }
    if (this.vignetteTimer > 0) this.vignetteTimer -= dt;
    this.vignette.style.opacity = String(Math.max(0, this.vignetteTimer / 0.35) * 0.55);
  }

  clearTransient() {
    for (const a of this.dmgArcs) {
      a.t = 0;
      a.e.style.opacity = '0';
    }
    this.vignetteTimer = 0;
    this.hitTimer = 0;
    this.hitmarker.classList.remove('iv-show');
    this.bannerTimer = 0;
    this.banner.classList.remove('iv-show');
    this.killFeed.replaceChildren();
    this._killKey = '';
  }

  /**
   * Per-frame refresh from real state.
   * @param {number} dt
   * @param {object} s  { weapon (WeaponHandle state), weaponLabel, player (controller state), health, maxHealth,
   *   alive, fps, showFps, sprinting, round (session.roundInfo()), zoneVec {distance, angle}, ownTeam, killFeed,
   *   death {killerName, killerColor, weapon, respawnIn, waiting} | null, allies [...] }
   */
  update(dt, s) {
    const w = s.weapon;
    if (w) {
      setText(this.weaponName, s.weaponLabel || w.name || '');
      setText(this.ammoMag, w.magazine);
      this.ammoChamber.classList.toggle('iv-on', w.chamber > 0);
      setText(this.ammoReserve, `/ ${w.reserve}`);
      this.ammoMag.classList.toggle('iv-low', w.magazine + w.chamber <= Math.max(3, Math.floor(w.capacity / 6)));
      const busy = w.state === 'reloading' || w.state === 'chambering';
      this.reloadBar.classList.toggle('iv-show', busy);
      this.reloadFill.style.transform = `scaleX(${w.reloadProgress.toFixed(3)})`;
      setText(this.reloadText, w.state === 'reloading' ? 'PŘEBÍJENÍ' : w.state === 'chambering' ? 'NABÍJENÍ' : w.magazine + w.chamber === 0 ? (w.reserve > 0 ? 'PRÁZDNO – R' : 'BEZ MUNICE') : '');
      setText(this.fireMode, w.fireMode === 'auto' ? 'DÁVKA' : 'JEDNOTLIVĚ');
      this.crosshair.style.opacity = String(s.alive === false ? 0 : Math.max(0, 1 - w.ads * 2.2) * (s.sprinting ? 0.35 : 1));
    }
    if (s.player) {
      const txt = s.alive === false ? '' : s.player.crouched ? 'DŘEP' : s.sprinting ? 'SPRINT' : '';
      setText(this.stance, txt);
    }
    if (typeof s.health === 'number') {
      setText(this.healthNum, s.health);
      const f = Math.max(0, Math.min(1, s.health / (s.maxHealth || 100)));
      this.healthFill.style.transform = `scaleX(${f.toFixed(3)})`;
      this.healthBox.classList.toggle('iv-low', f <= 0.3);
    }
    this._updateRound(s.round, s.zoneVec, s.ownTeam);
    this._updateKillFeed(s.killFeed || []);
    this._updateAllies(s.allies || []);
    // death overlay
    const d = s.death;
    this.death.classList.toggle('iv-show', !!d);
    this.ammoBox.classList.toggle('iv-dim', !!d);
    if (d) {
      if (d.killerName) {
        this.deathKiller.replaceChildren(el('span', '', 'Zabil tě '));
        const k = el('b', 'iv-kf-name', d.killerName);
        if (d.killerColor) k.style.color = d.killerColor;
        this.deathKiller.append(k);
        if (d.weapon) this.deathKiller.append(el('span', '', ` (${d.weapon})`));
      } else setText(this.deathKiller, d.forced ? 'Vyřazen testem' : '');
      setText(this.deathCount, d.waiting ? 'Čekám na bezpečné místo…' : `Návrat za ${Math.max(0, Math.ceil(d.respawnIn - 1e-6))} s`);
    }
    this.fps.style.display = s.showFps ? 'block' : 'none';
    if (s.showFps) setText(this.fps, `${(s.fps || 0).toFixed(0)} FPS`);
  }

  _updateRound(r, zv, ownTeam) {
    const matchMode = r && r.mode === 'match';
    this.top.classList.toggle('iv-show', !!matchMode);
    if (!matchMode) return;
    if (r.state === 'pre_round') setText(this.timer, `Start za ${Math.max(1, Math.ceil(r.preRoundS - 1e-6))} s`);
    else if (r.state === 'ended') setText(this.timer, 'Konec kola');
    else setText(this.timer, formatClock(r.remainingS));
    this.timer.classList.toggle('iv-urgent', r.state === 'running' && r.remainingS <= 60);
    for (let t = 0; t < this.teamEls.length; t++) {
      const e = this.teamEls[t];
      const team = r.teams[t];
      e.box.style.display = team ? '' : 'none';
      if (!team) continue;
      setText(e.name, team.name);
      setText(e.score, r.scores[t]);
      e.box.style.setProperty('--team', team.color || '#888');
      e.fill.style.transform = `scaleX(${Math.min(1, r.scores[t] / r.scoreTarget).toFixed(3)})`;
      e.box.classList.toggle('iv-own', t === ownTeam);
      e.box.classList.toggle('iv-lead', r.status === 'controlled' && r.controller === t);
    }
    setText(this.zoneName, r.zoneName || '');
    if (zv) {
      setText(this.zoneDist, zv.inside ? 'jsi v oblasti' : `${Math.round(zv.distance)} m`);
      this.zoneArrow.style.transform = `rotate(${(-zv.angle * 180) / Math.PI}deg)`;
      this.zoneArrow.style.visibility = zv.inside ? 'hidden' : 'visible';
    }
    let st = 'Prázdná';
    let col = '';
    if (r.state === 'pre_round') st = 'Čeká na start';
    else if (r.status === 'contested') st = 'Sporná';
    else if (r.status === 'controlled' && r.controller >= 0) {
      st = `Drží ${r.teams[r.controller].name}`;
      col = r.teams[r.controller].color;
    }
    setText(this.zoneState, st);
    this.zoneState.style.color = col;
    this.zone.style.setProperty('--zone', col || '#c8ccd0');
    this.zoneFill.style.transform = `scaleX(${(r.status === 'controlled' ? Math.min(1, r.progress) : 0).toFixed(3)})`;
  }

  _updateKillFeed(list) {
    const key = list.map((k) => `${k.attackerId}>${k.victimId}@${k.victimTeam}:${k.weapon}`).join('|') + `#${list.length}`;
    if (key === this._killKey) return;
    this._killKey = key;
    const color = (t) => (this.teamsData && this.teamsData.teams[t] ? this.teamsData.teams[t].color : '#ddd');
    const rows = list.map((k) => {
      const row = el('div', 'iv-kf-row');
      if (k.attackerName) {
        const a = el('b', 'iv-kf-name', k.attackerName);
        a.style.color = color(k.attackerTeam);
        row.append(a, el('span', 'iv-kf-weapon', ` ${k.weapon || '✕'}${k.headshot ? ' ◎' : ''} `));
      } else row.append(el('span', 'iv-kf-weapon', '✕ '));
      const v = el('b', 'iv-kf-name', k.victimName);
      v.style.color = color(k.victimTeam);
      row.append(v);
      return row;
    });
    this.killFeed.replaceChildren(...rows);
  }

  _updateAllies(list) {
    const seen = new Set();
    for (const a of list) {
      seen.add(a.id);
      let e = this.allyEls.get(a.id);
      if (!e) {
        const box = el('div', 'iv-ally');
        const name = el('span', 'iv-ally-name', '');
        const dist = el('span', 'iv-ally-dist', '');
        const pip = el('i', 'iv-ally-pip');
        box.append(pip, name, dist);
        this.allies.append(box);
        e = { box, name, dist };
        this.allyEls.set(a.id, e);
      }
      e.box.style.display = a.onScreen ? '' : 'none';
      if (!a.onScreen) continue;
      setText(e.name, a.name);
      setText(e.dist, `${Math.round(a.distance)} m`);
      e.box.style.setProperty('--team', a.color);
      e.box.style.transform = `translate(${a.x.toFixed(1)}px, ${a.y.toFixed(1)}px) translate(-50%, -100%)`;
    }
    for (const [id, e] of this.allyEls) {
      if (!seen.has(id)) {
        e.box.remove();
        this.allyEls.delete(id);
      }
    }
  }

  /** Visible text of the main HUD fields (tests read exactly what the player sees). */
  getState() {
    return {
      visible: this.hud.classList.contains('iv-open'),
      health: this.healthNum.textContent,
      ammoMag: this.ammoMag.textContent,
      ammoChamber: this.ammoChamber.classList.contains('iv-on'),
      ammoReserve: this.ammoReserve.textContent,
      weapon: this.weaponName.textContent,
      fireMode: this.fireMode.textContent,
      reloadVisible: this.reloadBar.classList.contains('iv-show'),
      reloadText: this.reloadText.textContent,
      timer: this.timer.textContent,
      scores: this.teamEls.map((e) => e.score.textContent),
      teamNames: this.teamEls.map((e) => e.name.textContent),
      zoneName: this.zoneName.textContent,
      zoneDist: this.zoneDist.textContent,
      zoneState: this.zoneState.textContent,
      topVisible: this.top.classList.contains('iv-show'),
      killFeed: [...this.killFeed.children].map((r) => r.textContent),
      allies: [...this.allyEls.entries()].map(([id, e]) => ({ id, visible: e.box.style.display !== 'none', text: e.box.textContent })),
      deathVisible: this.death.classList.contains('iv-show'),
      deathText: this.death.textContent,
      stance: this.stance.textContent,
      banner: this.banner.classList.contains('iv-show') ? this.banner.textContent : '',
      notice: this.notice.classList.contains('iv-show') ? this.notice.textContent : '',
      damageArcs: this.dmgArcs.filter((a) => a.t > 0).length,
      hitmarker: this.hitmarker.classList.contains('iv-show'),
    };
  }
}
