// Entry point of the IRON VALLEY browser build (test range).

import { Game } from './game/game.js';
import { isWebGL2Available } from './engine/renderer.js';
import { installTestApi } from './debug/testApi.js';

function showError(root, message) {
  const box = document.createElement('div');
  box.className = 'iv-error';
  box.textContent = message;
  root.appendChild(box);
}

async function boot() {
  let root = document.getElementById('iv-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'iv-root';
    document.body.appendChild(root);
  }
  if (!isWebGL2Available()) {
    showError(root, 'Tento prohlížeč nepodporuje WebGL2, hru nelze spustit. Zkus aktuální Chrome, Edge nebo Firefox.');
    return;
  }
  const game = new Game(root);
  // The test interface is installed before init so tests can wait on it; the game itself
  // never depends on it.
  window.__IV_BOOT = { status: 'loading' };
  try {
    await game.init();
    installTestApi(game);
    window.__IV_BOOT = { status: 'ready' };
  } catch (err) {
    console.error('[boot] failed to start:', err);
    window.__IV_BOOT = { status: 'error', message: String(err && err.message) };
    showError(root, `Hru se nepodařilo spustit: ${err && err.message ? err.message : err}`);
  }
}

boot();
