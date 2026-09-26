// Match flow on the real build: menus (UI-01), loadout, HUD with real values, pause / core menu lock
// (GUN-03), HUD ammo = core state through reloads and interruptions (GUN-01), death and respawn (GAME-02),
// friendly fire off, spawn safety with scripted enemies, full round to the results screen and "Nové kolo",
// 17- and 3-bot runs with the AI, HUD layout at 960x540 and 1920x1080, levels by id.
// Deterministic scenarios switch the AI off (setAIEnabled(false)) and drive bots through the same
// applyCommand path; the AI runs in the dedicated bot-count test.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { launchGame, screenshot } from './helpers.mjs';

let g;
let page;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  page = g.page;
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

const ev = (fn, arg) => page.evaluate(fn, arg);
const menuScreen = () => ev(() => window.__IV.getState().menuScreen);
const pointerLocked = () => ev(() => !!document.pointerLockElement);

/** Snapshot of HUD text vs the core weapon state of the player's active weapon. */
const hudVsCore = () =>
  ev(() => {
    const iv = window.__IV;
    iv.renderNow(); // HUD refresh happens in the frame update
    const h = iv.getHud();
    const c = iv.getCoreWeapon();
    return { hud: { mag: h.ammoMag, chamber: h.ammoChamber, reserve: h.ammoReserve, reload: h.reloadVisible, text: h.reloadText, weapon: h.weapon }, core: { mag: c.magazine, chamber: c.chamber, reserve: c.reserve, state: c.state } };
  });
const assertHudMatchesCore = (r, label) => {
  assert.equal(r.hud.mag, String(r.core.mag), `${label}: HUD magazine ${r.hud.mag} vs core ${r.core.mag}`);
  assert.equal(r.hud.chamber, r.core.chamber === 1, `${label}: HUD chamber`);
  assert.equal(r.hud.reserve, `/ ${r.core.reserve}`, `${label}: HUD reserve`);
  assert.equal(r.hud.reload, r.core.state === 'reloading' || r.core.state === 'chambering', `${label}: reload bar`);
};

/** A match without menus, AI off, loop frozen (tests step the simulation). */
async function freshMatch(opts = {}) {
  await ev(async (o) => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ bots: [2, 2, 2], seed: 42, skipPreRound: true, ai: false, ...o });
    iv.pause();
    iv.releaseAll();
    iv.step(2);
  }, opts);
}

test('UI-01: title menu, settings (sensitivity, FOV, volume, key rebinding), controls; Esc goes back; cursor never trapped', async () => {
  assert.equal(await menuScreen(), 'title');
  const title = await ev(() => window.__IV.getMenu());
  assert.deepEqual(
    title.buttons.filter((b) => !b.action.startsWith('map-')).map((b) => b.text),
    ['Začít', 'Trénink (bez botů)', 'Nastavení', 'Ovládání', 'Ukončit'],
  );
  await screenshot(page, 'menu_title.png');
  await page.click('button[data-action="settings"]');
  assert.equal(await menuScreen(), 'settings');
  const set = async (key, value) =>
    ev(
      ({ key, value }) => {
        const input = document.querySelector(`input[data-setting="${key}"]`);
        input.value = String(value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return window.__IV.getState().settings[key];
      },
      { key, value },
    );
  assert.equal(await set('mouseSensitivity', 1.5), 1.5);
  assert.equal(await set('fovDeg', 95), 95);
  assert.equal(await set('masterVolume', 0.3), 0.3);
  const stored = await ev(() => JSON.parse(localStorage.getItem('ironvalley.settings.v1')));
  assert.equal(stored.mouseSensitivity, 1.5);
  assert.equal(stored.fovDeg, 95);
  const audio = await ev(() => window.__IV.getState().audio);
  assert.equal(audio.unlocked, true, 'audio context created on the first menu click');
  assert.ok(Math.abs(audio.masterGain - 0.3) < 1e-6, `master gain ${audio.masterGain}`);
  // key rebinding: jump -> J (real keyboard), Esc cancels a capture
  await page.click('button[data-action="bind-jump"]');
  await page.keyboard.press('KeyJ');
  let b = await ev(() => window.__IV.getState().bindings);
  assert.deepEqual(b.jump, ['KeyJ']);
  await page.click('button[data-action="bind-crouch"]');
  await page.keyboard.press('Escape');
  b = await ev(() => window.__IV.getState().bindings);
  assert.deepEqual(b.crouch, ['KeyC', 'ControlLeft'], 'Esc cancels the capture');
  assert.equal(await menuScreen(), 'settings', 'Esc during capture does not leave the screen');
  const persisted = await ev(() => JSON.parse(localStorage.getItem('ironvalley.bindings.v1')));
  assert.deepEqual(persisted.jump, ['KeyJ']);
  await screenshot(page, 'menu_settings.png');
  await page.keyboard.press('Escape');
  assert.equal(await menuScreen(), 'title', 'Esc returns from settings');
  await page.click('button[data-action="controls"]');
  const ctl = await ev(() => document.querySelector('.iv-menu').textContent);
  assert.match(ctl, /Cíl hry/);
  assert.match(ctl, /Skok\s*J/, 'controls screen shows the rebound key');
  await page.click('button[data-action="back"]');
  assert.equal(await menuScreen(), 'title');
  await page.click('button[data-action="quit"]');
  assert.equal(await menuScreen(), 'quit');
  assert.match(await ev(() => document.querySelector('.iv-menu').textContent), /zavřením karty/);
  await page.click('button[data-action="back"]');
  assert.equal(await pointerLocked(), false);
});

test('loadout -> "Do boje": iron sights chosen and shown, HUD shows real values, rebound key works in play', async () => {
  await page.click('.iv-btn-primary'); // Začít
  assert.equal(await menuScreen(), 'loadout');
  await page.click('button[data-action="optic-irons"]');
  const lo = await ev(() => document.querySelector('.iv-menu').textContent);
  assert.match(lo, /IV-7 karabina/);
  assert.match(lo, /IV-P9 pistole/);
  assert.match(lo, /30\+1 nábojů/);
  const pressed = await ev(() => document.querySelector('button[data-action="optic-irons"]').getAttribute('aria-pressed'));
  assert.equal(pressed, 'true');
  await screenshot(page, 'menu_loadout.png');
  await page.click('.iv-btn-primary'); // Do boje
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  const r = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    iv.setAIEnabled(false);
    iv.step(1);
    iv.renderNow();
    return { s: iv.getState(), hud: iv.getHud(), m: iv.getMatchState() };
  });
  assert.equal(r.s.mode, 'match');
  assert.equal(r.s.optic, 'irons');
  assert.ok(r.s.weaponAsset.hiddenNodes > 0, 'optic nodes hidden for iron sights');
  assert.match(r.hud.weapon, /mechanická mířidla/);
  assert.equal(r.hud.health, '100');
  assert.equal(r.hud.ammoMag, '30');
  assert.equal(r.hud.ammoChamber, true);
  assert.equal(r.hud.ammoReserve, '/ 90');
  assert.deepEqual(r.hud.teamNames, ['Alfa', 'Bravo', 'Charlie']);
  assert.equal(r.hud.zoneName, r.m.zoneName);
  assert.match(r.hud.timer, /^Start za \d s$/, `pre-round timer ${r.hud.timer}`);
  assert.equal(r.m.state, 'pre_round');
  assert.equal(r.hud.allies.length, 5, 'markers for the 5 allies');
  // rebound jump key in play
  const jumps = await ev(() => {
    const iv = window.__IV;
    iv.step(20);
    const j0 = iv.getState().player.stats.jumps;
    iv.keyDown('Space');
    iv.step(2);
    iv.keyUp('Space');
    iv.step(40);
    const j1 = iv.getState().player.stats.jumps;
    iv.keyDown('KeyJ');
    iv.step(2);
    iv.keyUp('KeyJ');
    iv.step(40);
    return { j0, j1, j2: iv.getState().player.stats.jumps };
  });
  assert.equal(jumps.j1, jumps.j0, 'Space no longer jumps');
  assert.equal(jumps.j2, jumps.j0 + 1, 'J jumps');
  await ev(() => window.__IV._game.bindingsStore.reset());
});

test('HUD in play (screenshot): allies marked through walls, enemies visible as placeholder soldiers', async () => {
  await freshMatch({ bots: [3, 2, 2], seed: 9 });
  const r = await ev(() => {
    const iv = window.__IV;
    iv.placeCombatant('player', 0, 0, 12, 0);
    iv.placeCombatant('bot_1_0', -3, 0, 2, 180);
    iv.placeCombatant('bot_2_0', 3, 0, 4, 200);
    iv.placeCombatant('bot_0_0', -12, 0, -20, 0); // ally behind the window wall: marker through the wall
    iv.placeCombatant('bot_0_1', 6, 0, 9, 0);
    iv.step(10);
    iv.setDrawEnabled(true);
    iv.step(1, { render: true });
    return { hud: iv.getHud(), views: iv.getCombatantViews() };
  });
  const ally = r.hud.allies.find((a) => a.id === 'bot_0_0');
  assert.ok(ally && ally.visible && /Sokol/.test(ally.text), JSON.stringify(r.hud.allies));
  assert.ok(r.views.filter((v) => v.visible).length >= 4);
  assert.ok(r.views.every((v) => v.bones === 20), 'mannequin joints named like the UE skeleton');
  await screenshot(page, 'hud_play.png');
  await ev(() => window.__IV.setDrawEnabled(false));
});

test('Esc (real keyboard) pauses with the core menu lock; nothing fires; "Pokračovat" resumes and a held trigger needs a new press (GUN-03, UI-01)', async () => {
  await freshMatch();
  await ev(() => window.__IV.placeCombatant('player', 0, 0, 12, 0, 20));
  await ev(() => window.__IV.resume()); // real-time loop so real input is processed
  await page.mouse.move(480, 270);
  await page.mouse.down({ button: 'left' });
  const firing = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    const before = iv.getState().weapon.shotsFired;
    iv.frames(1 / 60, 20, { render: false });
    return iv.getState().weapon.shotsFired - before;
  });
  assert.ok(firing >= 3, `fires before Esc: ${firing}`);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.__IV.getState().state === 'paused');
  const paused = await ev(() => {
    const iv = window.__IV;
    const before = iv.getState().weapon.shotsFired;
    iv.frames(1 / 60, 60, { render: false });
    const s = iv.getState();
    return { shots: s.weapon.shotsFired - before, locks: iv.getCoreWeapon().disabledBy, enabled: s.input.enabled, menu: s.menuScreen };
  });
  assert.equal(paused.shots, 0);
  assert.ok(paused.locks.includes('menu'), `core menu lock: ${paused.locks}`);
  assert.equal(paused.enabled, false);
  assert.equal(paused.menu, 'paused');
  assert.equal(await pointerLocked(), false);
  await page.click('button[data-action="settings"]');
  await ev(() => {
    const input = document.querySelector('input[data-setting="fovDeg"]');
    input.value = '90';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await ev(() => window.__IV.renderNow());
  await screenshot(page, 'pause_settings.png');
  await page.click('button[data-action="back"]');
  assert.equal(await menuScreen(), 'paused');
  await ev(() => window.__IV.renderNow());
  await screenshot(page, 'pause_menu_match.png');
  await page.mouse.up({ button: 'left' });
  await page.click('.iv-btn-primary'); // Pokračovat
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  const resumed = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    const s = iv.getState();
    return { locks: iv.getCoreWeapon().disabledBy, fov: s.camera.fovHorizontalSetting };
  });
  assert.ok(!resumed.locks.includes('menu'));
  assert.equal(resumed.fov, 90, 'setting from the pause menu took effect');
  const afterPress = await ev(() => {
    const iv = window.__IV;
    const before = iv.getState().weapon.shotsFired;
    iv.mouseButton(0, true);
    iv.step(3);
    iv.mouseButton(0, false);
    iv.step(1);
    return iv.getState().weapon.shotsFired - before;
  });
  assert.ok(afterPress >= 1, 'a new press fires after resume');
});

test('GUN-01 in game: HUD ammo equals the core state after partial / empty reloads and interruptions (switch, sprint)', async () => {
  await freshMatch();
  await ev(() => window.__IV.placeCombatant('player', 0, 0, 12, 0, 30));
  const fire = (ticks) =>
    ev((t) => {
      const iv = window.__IV;
      iv.mouseButton(0, true);
      iv.step(t);
      iv.mouseButton(0, false);
      iv.step(1);
    }, ticks);
  const key = (code, ticks = 1) =>
    ev(
      ({ code, ticks }) => {
        const iv = window.__IV;
        iv.keyDown(code);
        iv.step(1);
        iv.keyUp(code);
        iv.step(ticks);
      },
      { code, ticks },
    );
  assertHudMatchesCore(await hudVsCore(), 'full');
  await fire(40); // 750 rpm: ~8 rounds
  let r = await hudVsCore();
  assertHudMatchesCore(r, 'after firing');
  assert.ok(r.core.mag < 30 && r.core.chamber === 1);
  await key('KeyR', 30); // tactical reload, 0.5 s in (before the insert)
  r = await hudVsCore();
  assert.equal(r.core.state, 'reloading');
  assert.equal(r.hud.text, 'PŘEBÍJENÍ');
  assertHudMatchesCore(r, 'mid reload');
  await ev(() => window.__IV.step(120));
  r = await hudVsCore();
  assertHudMatchesCore(r, 'after tactical reload');
  assert.deepEqual([r.core.mag, r.core.chamber], [30, 1]);
  // reload interrupted by a weapon switch before the insert: nothing changes
  await fire(20);
  const beforeSwitch = await hudVsCore();
  await key('KeyR', 20);
  await key('Digit2', 40);
  r = await hudVsCore();
  assert.match(r.hud.weapon, /IV-P9 pistole/);
  assertHudMatchesCore(r, 'pistol');
  assert.deepEqual([r.core.mag, r.core.chamber, r.core.reserve], [15, 1, 45]);
  await ev(() => window.__IV.setDrawEnabled(true));
  await ev(() => window.__IV.step(1, { render: true }));
  await screenshot(page, 'pistol_placeholder.png');
  await ev(() => window.__IV.setDrawEnabled(false));
  await key('Digit1', 40);
  r = await hudVsCore();
  assert.deepEqual([r.core.mag, r.core.chamber, r.core.reserve], [beforeSwitch.core.mag, beforeSwitch.core.chamber, beforeSwitch.core.reserve], 'switch before insert changed nothing');
  assertHudMatchesCore(r, 'rifle again');
  // empty the rifle; the trigger pull on empty starts an empty reload; sprint after the insert interrupts it
  await fire(260);
  r = await hudVsCore();
  assert.equal(r.core.mag + r.core.chamber, 0, JSON.stringify(r));
  assertHudMatchesCore(r, 'empty');
  await ev(() => {
    const iv = window.__IV;
    iv.mouseButton(0, true);
    iv.step(1);
    iv.mouseButton(0, false);
    iv.step(96); // 1.6 s: past the insert (1.3 s), before the bolt release (2.3 s)
  });
  r = await hudVsCore();
  assert.equal(r.core.state, 'reloading');
  assert.equal(r.core.mag, 30);
  assertHudMatchesCore(r, 'empty reload after insert');
  await ev(() => {
    const iv = window.__IV;
    iv.keyDown('KeyW');
    iv.keyDown('ShiftLeft');
    iv.step(10);
    iv.keyUp('KeyW');
    iv.keyUp('ShiftLeft');
    iv.step(40);
  });
  r = await hudVsCore();
  assert.deepEqual([r.core.state, r.core.mag, r.core.chamber], ['ready', 30, 0]);
  assertHudMatchesCore(r, 'sprint interrupted after insert');
  await fire(1); // chamber action, no shot
  await ev(() => window.__IV.step(60));
  r = await hudVsCore();
  assert.deepEqual([r.core.mag, r.core.chamber], [29, 1]);
  assertHudMatchesCore(r, 'after the chamber action');
});

test('GUN-03 + GAME-02: the player dies 3 times (forced, shot by an enemy, forced mid-reload); no fire while dead; every respawn restores health, ammo, controls, camera and view', async () => {
  await freshMatch({ bots: [0, 1, 0], seed: 3 });
  const hist = [];
  for (let n = 1; n <= 3; n++) {
    await ev((n) => {
      const iv = window.__IV;
      iv.placeCombatant('player', 0, 0, 10, 0, 25);
      iv.placeCombatant('bot_1_0', 0, 0, -12, 180);
      iv.step(2);
      if (n === 3) {
        iv.mouseButton(0, true);
        iv.step(10);
        iv.mouseButton(0, false);
        iv.keyDown('KeyR');
        iv.step(1);
        iv.keyUp('KeyR');
        iv.step(20); // mid reload
      }
    }, n);
    if (n === 2) {
      // shot dead by the enemy bot through the same weapon code path (bot driven with fire)
      const res = await ev(() => {
        const iv = window.__IV;
        let guard = 0;
        while (iv.getState().player.alive && guard++ < 40) {
          const p = iv.listCombatants().find((c) => c.isPlayer).position;
          iv.aimCombatant('bot_1_0', p[0], p[1] + 1.6, p[2]);
          iv.driveBot('bot_1_0', { fire: true }, 8);
          iv.driveBot('bot_1_0', { fire: false }, 4);
        }
        return { alive: iv.getState().player.alive, log: iv.getDeathLog().at(-1), hud: iv.getHud() };
      });
      assert.equal(res.alive, false, 'killed by the enemy');
      assert.equal(res.log.attackerId, 'bot_1_0');
      assert.ok(res.hud.damageArcs >= 1, 'damage direction indicator shown');
    } else {
      assert.equal(await ev(() => window.__IV.forceKill('player')), 'killed');
    }
    // dead: holding fire does nothing, death view with countdown
    const dead = await ev(() => {
      const iv = window.__IV;
      iv.placeCombatant('bot_1_0', -34, 0, -36, 90); // far away: the spawn is safe
      const before = iv.getState().weapon.shotsFired;
      iv.mouseButton(0, true);
      iv.keyDown('KeyR');
      iv.step(60);
      iv.renderNow();
      const s = iv.getState();
      return { shots: s.weapon.shotsFired - before, hud: iv.getHud(), locks: iv.getCoreWeapon().disabledBy, camY: s.camera.position[1], feetY: s.player.position.y, reload: s.weapon.state };
    });
    assert.equal(dead.shots, 0, `death ${n}: no shots while dead`);
    assert.ok(dead.locks.includes('life'));
    assert.notEqual(dead.reload, 'reloading');
    assert.equal(dead.hud.deathVisible, true);
    assert.match(dead.hud.deathText, /Návrat za \d s/);
    assert.ok(dead.camY - dead.feetY < 1.2, 'death camera sinks');
    if (n === 2) {
      assert.match(dead.hud.deathText, /Zabil tě/);
      await ev(() => {
        window.__IV.setDrawEnabled(true);
        window.__IV.step(1, { render: true });
      });
      await screenshot(page, 'death_view.png');
      await ev(() => window.__IV.setDrawEnabled(false));
    }
    const back = await ev(() => {
      const iv = window.__IV;
      const held = iv.getState().weapon.shotsFired;
      iv.step(60 * 5); // respawn happens in here, the trigger stays held
      iv.keyUp('KeyR');
      iv.step(20);
      const heldShots = iv.getState().weapon.shotsFired - held;
      iv.mouseButton(0, false);
      iv.step(1);
      iv.renderNow();
      const s = iv.getState();
      return { s, hud: iv.getHud(), heldShots, spawn: iv.getSpawnHistory().filter((h) => h.id === 'player').at(-1) };
    });
    assert.equal(back.s.player.alive, true, `respawn ${n}`);
    assert.equal(back.heldShots, 0, 'trigger held through the respawn does not fire');
    assert.equal(back.hud.health, '100');
    assert.equal(back.hud.ammoMag, '30');
    assert.equal(back.hud.ammoChamber, true);
    assert.equal(back.hud.ammoReserve, '/ 90');
    assert.equal(back.hud.deathVisible, false);
    assert.equal(back.s.weapon.state, 'ready');
    assert.equal(back.s.player.activeWeapon, 0);
    assert.ok(Math.abs(back.s.camera.position[1] - (back.spawn.position[1] + 1.65)) < 0.05, `camera at eye height ${back.s.camera.position[1]}`);
    assert.ok(back.spawn.safeAtSpawn && back.spawn.nearestEnemy >= 20 && back.spawn.visibleToEnemy === null && !back.spawn.insideGeometry, JSON.stringify(back.spawn));
    hist.push(back.spawn);
    const ctl = await ev(() => {
      const iv = window.__IV;
      const p0 = iv.getState().player.position;
      iv.keyDown('KeyW');
      iv.step(30);
      iv.keyUp('KeyW');
      iv.step(10);
      const p1 = iv.getState().player.position;
      const s0 = iv.getState().weapon.shotsFired;
      iv.mouseButton(0, true);
      iv.step(1);
      iv.mouseButton(0, false);
      iv.step(1);
      return { moved: Math.hypot(p1.x - p0.x, p1.z - p0.z), shots: iv.getState().weapon.shotsFired - s0 };
    });
    assert.ok(ctl.moved > 0.5, `controls: moved ${ctl.moved}`);
    assert.equal(ctl.shots, 1, 'a new press fires after the respawn');
    if (n === 1) {
      await ev(() => {
        window.__IV.setDrawEnabled(true);
        window.__IV.step(1, { render: true });
      });
      await screenshot(page, 'after_respawn.png');
      await ev(() => window.__IV.setDrawEnabled(false));
    }
  }
  const deaths = await ev(() => window.__IV.listCombatants().find((c) => c.isPlayer).deaths);
  assert.equal(deaths, 3);
  assert.equal(hist.length, 3);
});

test('friendly fire is off in game; enemy hits apply zone damage, hit marker and kill feed', async () => {
  await freshMatch({ bots: [1, 1, 0], seed: 5 });
  const r = await ev(() => {
    const iv = window.__IV;
    iv.placeCombatant('player', 0, 0, 10, 0, 0);
    iv.placeCombatant('bot_0_0', 0, 0, 2, 180);
    iv.placeCombatant('bot_1_0', 6, 0, 0, 200);
    iv.step(5);
    const shoot = (x, y, z) => {
      iv.lookAt(x, y, z);
      iv.step(40);
      iv.mouseButton(0, true);
      iv.step(1);
      iv.mouseButton(0, false);
      iv.step(1);
      iv.renderNow();
      return iv.getHud();
    };
    const ally = iv.listCombatants().find((c) => c.id === 'bot_0_0');
    const h1 = shoot(ally.position[0], 1.2, ally.position[2]);
    const allyAfter = iv.listCombatants().find((c) => c.id === 'bot_0_0').health;
    const ffBlocked = iv.getMatchState().stats.ffBlocked;
    const h2 = shoot(6, 1.2, 0);
    const enemyAfterTorso = iv.listCombatants().find((c) => c.id === 'bot_1_0').health;
    const eyeY = 1.65 + 0.03;
    shoot(6, eyeY, 0);
    const h3 = shoot(6, eyeY, 0);
    iv.renderNow();
    return { h1, allyAfter, ffBlocked, h2, enemyAfterTorso, h3, enemy: iv.listCombatants().find((c) => c.id === 'bot_1_0'), feed: iv.getMatchState().killFeed };
  });
  assert.equal(r.allyAfter, 100, 'ally unharmed');
  assert.equal(r.ffBlocked, 1);
  assert.equal(r.h1.hitmarker, false, 'no hit marker on a friendly');
  assert.equal(r.enemyAfterTorso, 66, 'torso 34');
  assert.equal(r.h2.hitmarker, true);
  assert.equal(r.enemy.alive, false, JSON.stringify(r.enemy));
  assert.ok(r.feed.some((k) => k.attackerId === 'player' && k.victimId === 'bot_1_0' && k.headshot), JSON.stringify(r.feed));
  assert.ok(r.h3.killFeed.some((t) => /Ty/.test(t) && /Havran/.test(t)), JSON.stringify(r.h3.killFeed));
});

test('spawn safety (scripted enemy placement): no spawn next to enemies, in view of enemies or inside geometry; the player waits', async () => {
  await freshMatch({ bots: [0, 2, 0], seed: 8 });
  const r = await ev(() => {
    const iv = window.__IV;
    iv.forceKill('player');
    iv.placeCombatant('bot_1_0', 34.5, 0, 26, 0); // inside the Alfa shelter
    iv.placeCombatant('bot_1_1', 25, 0, 29, 90); // at its entrance
    iv.step(60 * 8);
    iv.renderNow();
    const waiting = { state: iv.listCombatants().find((c) => c.isPlayer).state, hud: iv.getHud(), blocked: iv.getMatchState().spawnBlocked };
    iv.placeCombatant('bot_1_0', -34, 0, -36, 90);
    iv.placeCombatant('bot_1_1', -36, 0, -33, 90);
    iv.step(40);
    const spawn = iv.getSpawnHistory().filter((h) => h.id === 'player').at(-1);
    return {
      waiting,
      alive: iv.getState().player.alive,
      spawn,
      inside: iv.evaluateSpawnPoint(0, 0, -15, 0),
      all: iv.getSpawnHistory(),
    };
  });
  assert.equal(r.waiting.state, 'respawning', 'waits while every point is unsafe');
  assert.match(r.waiting.hud.deathText, /Čekám na bezpečné místo/);
  assert.ok(r.waiting.blocked > 0);
  assert.equal(r.alive, true);
  assert.ok(r.spawn.safeAtSpawn && r.spawn.nearestEnemy >= 20 && r.spawn.visibleToEnemy === null && !r.spawn.insideGeometry, JSON.stringify(r.spawn));
  assert.ok(r.inside.reasons.includes('inside_geometry'));
  for (const h of r.all) assert.ok(h.safeAtSpawn, JSON.stringify(h));
});

test('full round to the results screen (score target) and "Nové kolo" restarts everything cleanly', async () => {
  await ev(async () => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ bots: [0, 0, 0], seed: 21, ai: false });
    iv.pause();
    iv.releaseAll();
  });
  const pre = await ev(() => {
    const iv = window.__IV;
    const m = iv.getMatchState();
    const z = m.zone;
    // a few impacts on the thin wall (decals must be gone after the reset)
    iv.placeCombatant('player', 21, 0, -1.2, 0, 0);
    iv.lookAt(21.4, 1.4, -3.95);
    iv.step(10);
    iv.mouseButton(0, true);
    iv.step(10);
    iv.mouseButton(0, false);
    iv.step(1);
    const decals = iv.getState().effects.decals;
    iv.placeCombatant('player', z.center[0], z.center[1], z.center[2], 0, 0);
    return { m, decals };
  });
  assert.equal(pre.m.state, 'pre_round');
  assert.ok(pre.decals > 0);
  const t = await ev(() => window.__IV.simulateUntil({ gameState: 'results' }, 400));
  const res = await ev(() => ({ m: window.__IV.getMatchState(), menu: window.__IV.getMenu(), text: document.querySelector('.iv-menu').textContent, locked: !!document.pointerLockElement }));
  assert.ok(t > 200 && t < 212, `round took ${t} s of simulation`);
  assert.equal(res.m.gameState, 'results');
  assert.equal(res.m.endReason, 'score_target');
  assert.deepEqual(res.m.scores, [100, 0, 0]);
  assert.match(res.text, /Vítězí tým Alfa/);
  assert.match(res.text, /dosažením 100 bodů/);
  assert.equal(res.locked, false, 'cursor free on the results screen');
  assert.deepEqual(res.menu.buttons.map((b) => b.text), ['Nové kolo', 'Změnit výbavu', 'Hlavní menu']);
  await ev(() => window.__IV.renderNow());
  await screenshot(page, 'results.png');
  await page.click('.iv-btn-primary'); // Nové kolo
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  const nr = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    iv.step(1);
    iv.renderNow();
    return { m: iv.getMatchState(), s: iv.getState(), hud: iv.getHud(), c: iv.listCombatants(), core: iv.getCoreWeapon() };
  });
  assert.equal(nr.m.roundNumber, 2);
  assert.equal(nr.m.state, 'pre_round');
  assert.deepEqual(nr.m.scores, [0, 0, 0]);
  assert.equal(nr.m.elapsedS, 0);
  assert.equal(nr.m.killFeed.length, 0);
  assert.equal(nr.s.effects.decals, 0, 'decals cleared');
  assert.equal(nr.hud.scores.join(','), '0,0,0');
  assert.match(nr.hud.timer, /Start za 5 s/);
  assert.equal(nr.hud.banner, '');
  assert.equal(nr.c[0].alive, true);
  assert.equal(nr.c[0].spawnCount, 1);
  assert.equal(nr.c[0].health, 100);
  assert.deepEqual([nr.core.magazine, nr.core.chamber, nr.core.reserve], [30, 1, 90]);
  assert.ok(!nr.core.disabledBy.includes('results'));
  assert.ok(nr.s.events.some((e) => e.type === 'round-reset'));
  // the new round plays: pre-round countdown runs into the round
  const run = await ev(() => {
    const iv = window.__IV;
    iv.step(60 * 6);
    return iv.getMatchState();
  });
  assert.equal(run.state, 'running');
  assert.ok(run.elapsedS > 0.9);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.__IV.getState().state === 'paused');
  await page.click('button[data-action="leave"]');
  assert.equal(await menuScreen(), 'title');
});

test('AI runs with 17 bots and with 3 bots (fast simulation, render off): bots move, fight and respawn; no errors', async () => {
  const r17 = await ev(async () => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ bots: [5, 6, 6], seed: 77, ai: true, skipPreRound: true });
    iv.pause();
    const start = iv.listCombatants().map((c) => c.position);
    const t0 = performance.now();
    iv.simulate(60);
    const ms = performance.now() - t0;
    const c = iv.listCombatants();
    const moved = c.filter((x, i) => !x.isPlayer && Math.hypot(x.position[0] - start[i][0], x.position[2] - start[i][2]) > 3).length;
    return { n: c.length, moved, deaths: iv.getDeathLog().length, m: iv.getMatchState(), msPerSimSecond: ms / 60, ai: iv.getAIDebug() };
  });
  console.log(`# 17 bots: moved ${r17.moved}, deaths ${r17.deaths}, scores ${r17.m.scores}, ${r17.msPerSimSecond.toFixed(1)} ms per simulated second (render off)`);
  assert.equal(r17.n, 18);
  assert.ok(r17.moved >= 10, `bots move (${r17.moved})`);
  assert.ok(r17.m.elapsedS > 59);
  assert.equal(r17.ai.stub, false);
  // screenshot of the live match: camera 9 m from a living bot with a clear line of sight to it
  const shot = await ev(() => {
    const iv = window.__IV;
    const game = iv._game;
    const wq = game.session.worldQuery;
    const V = game.camera.position.constructor;
    for (const b of iv.listCombatants().filter((c) => !c.isPlayer && c.alive)) {
      for (const [dx, dz] of [[0, 9], [9, 0], [-9, 0], [0, -9], [6, 6], [-6, 6], [6, -6], [-6, -6]]) {
        const x = b.position[0] + dx;
        const z = b.position[2] + dz;
        const e = iv.evaluateSpawnPoint(x, b.position[1], z, b.team);
        if (e.reasons.includes('inside_geometry') || e.reasons.includes('no_ground')) continue;
        if (!wq.lineOfSight(new V(x, b.position[1] + 1.65, z), new V(b.position[0], b.position[1] + 1.2, b.position[2]))) continue;
        iv.placeCombatant('player', x, b.position[1], z, 0, 0);
        iv.lookAt(b.position[0], b.position[1] + 1.1, b.position[2]);
        iv.setDrawEnabled(true);
        iv.step(1, { render: true });
        return { bot: b.id, visible: iv.getCombatantViews().filter((v) => v.visible).length };
      }
    }
    iv.setDrawEnabled(true);
    iv.step(1, { render: true });
    return { bot: null };
  });
  console.log(`# 17-bot screenshot framed on ${shot.bot}`);
  await screenshot(page, 'bots_17.png');
  const r3 = await ev(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false);
    const roster = iv.setBotCount([0, 1, 2]);
    iv.pause();
    iv.simulate(30);
    return { roster, m: iv.getMatchState() };
  });
  assert.equal(r3.roster.length, 4);
  assert.ok(r3.m.elapsedS > 24, `round clock runs after the 5 s pre-round (${r3.m.elapsedS})`);
});

test('HUD readable at 960x540 and 1920x1080: no text overflow, inside the viewport, main widgets do not overlap', async () => {
  await freshMatch({ bots: [5, 6, 6], seed: 1 });
  const measure = () =>
    ev(() => {
      const iv = window.__IV;
      iv.placeCombatant('player', 0, 0, 14, 0, 0);
      iv.forceKill('bot_1_0');
      iv.step(2);
      iv.renderNow();
      const W = window.innerWidth;
      const H = window.innerHeight;
      const bad = [];
      for (const el of document.querySelectorAll('.iv-hud *')) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('.iv-allies')) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0 || !el.textContent.trim()) continue;
        if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1) bad.push(`overflow ${el.className} ${el.scrollWidth}>${el.clientWidth}`);
        if (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1) bad.push(`outside ${el.className} ${JSON.stringify([r.left, r.top, r.right, r.bottom])}`);
      }
      const boxes = ['.iv-location', '.iv-top', '.iv-killfeed', '.iv-health', '.iv-ammo', '.iv-stance'].map((sel) => {
        const el = document.querySelector(sel);
        const r = el.getBoundingClientRect();
        return { sel, r: [r.left, r.top, r.right, r.bottom], vis: getComputedStyle(el).display !== 'none' && r.width > 0 && r.height > 0 };
      });
      const overlaps = [];
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i];
          const b = boxes[j];
          if (!a.vis || !b.vis) continue;
          if (a.r[0] < b.r[2] && b.r[0] < a.r[2] && a.r[1] < b.r[3] && b.r[1] < a.r[3]) overlaps.push(`${a.sel} x ${b.sel}`);
        }
      }
      const fs = parseFloat(getComputedStyle(document.querySelector('.iv-team-name')).fontSize);
      return { bad, overlaps, fs, hud: iv.getHud() };
    });
  const small = await measure();
  assert.deepEqual(small.bad, []);
  assert.deepEqual(small.overlaps, []);
  assert.ok(small.fs >= 11, `team name font ${small.fs}px`);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(300);
  const big = await measure();
  assert.deepEqual(big.bad, []);
  assert.deepEqual(big.overlaps, []);
  assert.ok(big.fs >= 13, `team name font at 1080p ${big.fs}px`);
  await ev(() => {
    window.__IV.setDrawEnabled(true);
    window.__IV.step(1, { render: true });
  });
  await screenshot(page, 'hud_1080p.png');
  await ev(() => window.__IV.setDrawEnabled(false));
  await page.setViewportSize({ width: 960, height: 540 });
  await page.waitForTimeout(300);
});

test('levels load by id: another level from the build, a missing one is refused, back to the test range', async () => {
  const r = await ev(async () => {
    const iv = window.__IV;
    const levels = iv.listLevels();
    const out = { levels };
    const other = levels.find((l) => l.id !== 'test_range');
    if (other) {
      const info = await iv.loadLevel(other.id);
      out.other = { info, state: iv.getState().levelId, mode: iv.getState().mode };
    }
    try {
      await iv.loadLevel('kalne_hamry_missing');
      out.missing = 'loaded?!';
    } catch (e) {
      out.missing = String(e.message);
    }
    out.back = await iv.loadLevel('test_range');
    out.after = iv.getState().levelId;
    return out;
  });
  assert.ok(r.levels.some((l) => l.id === 'test_range'));
  if (r.other) {
    assert.equal(r.other.state, r.other.info.id);
    assert.equal(r.other.mode, 'practice');
  }
  assert.match(r.missing, /není/);
  assert.equal(r.after, 'test_range');
});

test('pistol GLB drop-in path: a GLB with socket_muzzle / socket_ads replaces the placeholder and the gameplay muzzle follows its sockets (stand-in GLB)', async () => {
  // The real IVP9_Pistol.glb does not exist yet. The loader is exercised with the IV-7 GLB standing in
  // for it (it has the same socket names); this changes only this page's runtime state (last test).
  const r = await ev(async () => {
    const iv = window.__IV;
    const game = iv._game;
    const before = iv.getState().pistolAsset;
    game.data.weapons.ivp9_pistol.viewModel.asset = 'assets/weapons/IV7_Carbine.glb';
    await game.loadPistolAsset();
    iv.pause();
    await iv.startMatch({ bots: [0, 0, 0], seed: 2, ai: false, skipPreRound: true });
    iv.pause();
    iv.keyDown('Digit2');
    iv.step(1);
    iv.keyUp('Digit2');
    iv.step(40);
    const s = iv.getState();
    return { before, after: s.pistolAsset, active: s.player.activeWeapon, consistency: iv.muzzleConsistency(), def: game.weaponDef };
  });
  assert.equal(r.before.isPlaceholder, true);
  assert.equal(r.after.loaded, true);
  assert.equal(r.after.isPlaceholder, false);
  assert.equal(r.active, 1);
  // ADS position derived from socket_ads: socket at the camera
  assert.ok(r.consistency.adsEye.distance < 0.002, JSON.stringify(r.consistency.adsEye));
  assert.ok(r.consistency.hip.renderedDistance < 0.002 && r.consistency.ads.renderedDistance < 0.002, JSON.stringify(r.consistency));
  for (const tr of r.consistency.transition) assert.ok(tr.renderedDistance < 0.002, JSON.stringify(r.consistency.transition));
});
