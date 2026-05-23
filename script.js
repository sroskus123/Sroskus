const SERVER_CONFIG = {
  host: "144.76.87.106:25658",
  statusApiBase: "https://api.mcsrvstat.us/3/",
  refreshMs: 60_000,
};

const state = {
  currentRoute: "home",
  lastServerData: null,
  cityAnimationId: null,
};

const dom = {
  body: document.body,
  nav: document.querySelector("[data-nav]"),
  navToggle: document.querySelector("[data-nav-toggle]"),
  routeLinks: [...document.querySelectorAll("[data-route-link]")],
  pages: [...document.querySelectorAll("[data-page]")],
  serverChip: document.querySelector("[data-server-chip]"),
  chipText: document.querySelector("[data-chip-text]"),
  onlineCount: document.querySelector("[data-online-count]"),
  refreshStatus: document.querySelector("[data-refresh-status]"),
  statusState: document.querySelector("[data-status-state]"),
  statusPlayers: document.querySelector("[data-status-players]"),
  statusVersion: document.querySelector("[data-status-version]"),
  statusUpdated: document.querySelector("[data-status-updated]"),
  statusMotd: document.querySelector("[data-status-motd]"),
  playerList: document.querySelector("[data-player-list]"),
  playerTotal: document.querySelector("[data-player-total]"),
  platformModal: document.querySelector("[data-platform-modal]"),
  openPlatformModalButtons: [...document.querySelectorAll("[data-open-platform-modal]")],
  closePlatformModalButtons: [...document.querySelectorAll("[data-close-platform-modal]")],
  donateModal: document.querySelector("[data-donate-modal]"),
  donateModalCopy: document.querySelector("[data-donate-modal-copy]"),
  openDonateModalButtons: [...document.querySelectorAll("[data-open-donate-modal]")],
  closeDonateModalButtons: [...document.querySelectorAll("[data-close-donate-modal]")],
  storeTabButtons: [...document.querySelectorAll("[data-store-tab]")],
  storePanels: [...document.querySelectorAll("[data-store-panel]")],
  cityCanvas: document.querySelector("#cityCanvas"),
};

function init() {
  bindNavigation();
  bindStoreTabs();
  bindPlatformModal();
  bindDonateModal();
  dom.refreshStatus?.addEventListener("click", () => refreshServerStatus());
  initCityCanvas();
  routeTo(getRouteFromHash());
  refreshServerStatus();
  window.setInterval(refreshServerStatus, SERVER_CONFIG.refreshMs);
}

function bindStoreTabs() {
  dom.storeTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      showStoreTab(button.dataset.storeTab);
    });
  });
}

function showStoreTab(tabName = "ranks") {
  const nextTab = dom.storePanels.some((panel) => panel.dataset.storePanel === tabName) ? tabName : "ranks";

  dom.storeTabButtons.forEach((button) => {
    const isActive = button.dataset.storeTab === nextTab;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });

  dom.storePanels.forEach((panel) => {
    const isActive = panel.dataset.storePanel === nextTab;
    panel.hidden = !isActive;
    panel.classList.toggle("active", isActive);
  });
}

function bindNavigation() {
  dom.navToggle?.addEventListener("click", () => {
    const isOpen = dom.body.classList.toggle("nav-open");
    dom.navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  window.addEventListener("hashchange", () => {
    routeTo(getRouteFromHash());
  });

  dom.routeLinks.forEach((link) => {
    link.addEventListener("click", () => closeMobileNav());
  });
}

function bindPlatformModal() {
  if (!dom.platformModal) return;

  dom.openPlatformModalButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      openPlatformModal();
    });
  });

  dom.closePlatformModalButtons.forEach((button) => {
    button.addEventListener("click", () => closePlatformModal());
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.platformModal.hidden) {
      closePlatformModal();
    }
  });
}

function bindDonateModal() {
  if (!dom.donateModal) return;

  dom.openDonateModalButtons.forEach((button) => {
    button.addEventListener("click", () => {
      openDonateModal(button.dataset.rankDonate);
    });
  });

  dom.closeDonateModalButtons.forEach((button) => {
    button.addEventListener("click", () => closeDonateModal());
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.donateModal.hidden) {
      closeDonateModal();
    }
  });
}

function openPlatformModal() {
  if (!dom.platformModal) return;
  dom.platformModal.hidden = false;
  dom.body.classList.add("modal-open");
}

function closePlatformModal() {
  if (!dom.platformModal) return;
  dom.platformModal.hidden = true;
  dom.body.classList.remove("modal-open");
}

function openDonateModal(rankName) {
  if (!dom.donateModal) return;
  if (dom.donateModalCopy && rankName) {
    dom.donateModalCopy.textContent = `Donate for ${rankName} on Ko-fi, then open a Discord ticket so staff can verify your donation and assign your reward rank.`;
  }
  dom.donateModal.hidden = false;
  dom.body.classList.add("modal-open");
}

function closeDonateModal() {
  if (!dom.donateModal) return;
  dom.donateModal.hidden = true;
  dom.body.classList.remove("modal-open");
}

function getRouteFromHash() {
  const hash = window.location.hash.replace("#", "").trim();
  return hash || "home";
}

function routeTo(route) {
  const pageExists = dom.pages.some((page) => page.dataset.page === route);
  const nextRoute = pageExists ? route : "home";
  state.currentRoute = nextRoute;

  dom.pages.forEach((page) => {
    page.classList.toggle("active", page.dataset.page === nextRoute);
  });

  dom.routeLinks.forEach((link) => {
    const target = link.getAttribute("href")?.replace("#", "");
    link.classList.toggle("active", target === nextRoute);
  });

  document.title =
    nextRoute === "home"
      ? "Cybercraft2069 | Cyberpunk Minecraft Server"
      : `${titleCase(nextRoute)} | Cybercraft2069`;

  closePlatformModal();
  closeDonateModal();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function closeMobileNav() {
  dom.body.classList.remove("nav-open");
  dom.navToggle?.setAttribute("aria-expanded", "false");
}

async function refreshServerStatus() {
  setServerChip("checking", "Checking");

  try {
    const data = await fetchServerStatus();
    state.lastServerData = data;
    renderServerStatus(data);
  } catch (error) {
    renderServerFallback(error);
  }
}

async function fetchServerStatus() {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  const endpoint = `${SERVER_CONFIG.statusApiBase}${encodeURIComponent(SERVER_CONFIG.host)}`;

  try {
    const response = await fetch(endpoint, {
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Status API returned ${response.status}`);
    }

    return await response.json();
  } finally {
    window.clearTimeout(timeout);
  }
}

function renderServerStatus(data) {
  const online = Boolean(data.online);
  const onlinePlayers = Number(data.players?.online ?? 0);
  const maxPlayers = Number(data.players?.max ?? 0);
  const listedPlayers = normalizePlayers(data.players?.list);
  const version = data.version || data.protocol?.name || "Unknown";
  const motd = data.motd?.clean?.join(" ") || data.motd?.raw?.join(" ") || "No server message available.";

  setServerChip(online ? "online" : "offline", online ? "Online" : "Offline");
  setText(dom.onlineCount, online ? String(onlinePlayers) : "0");
  setText(dom.statusState, online ? "Online" : "Offline");
  setText(dom.statusPlayers, `${onlinePlayers} / ${maxPlayers || "--"}`);
  setText(dom.statusVersion, version);
  setText(dom.statusUpdated, formatTime(new Date()));
  setText(dom.statusMotd, online ? motd : "The configured server did not respond as online.");

  renderPlayerList(listedPlayers, onlinePlayers);
}

function renderServerFallback(error) {
  console.warn("Server status failed:", error);
  setServerChip("offline", "Unavailable");
  setText(dom.onlineCount, "0");
  setText(dom.statusState, "Unavailable");
  setText(dom.statusPlayers, "0 / --");
  setText(dom.statusVersion, "Unknown");
  setText(dom.statusUpdated, formatTime(new Date()));
  setText(
    dom.statusMotd,
    `Could not reach ${SERVER_CONFIG.host}. Try refreshing in a moment.`
  );
  renderPlayerList([], 0);
}

function normalizePlayers(players) {
  if (!Array.isArray(players)) return [];

  return players
    .map((player) => {
      if (typeof player === "string") return { name: player };
      return { name: player.name || "Unknown" };
    })
    .filter((player) => player.name && player.name !== "Unknown");
}

function renderPlayerList(players, onlineCount) {
  if (!dom.playerList) return;

  const safePlayers = players.slice(0, 24);
  setText(dom.playerTotal, `${safePlayers.length || onlineCount || 0} listed`);

  if (!safePlayers.length) {
    dom.playerList.innerHTML = `<li><span class="player-avatar player-avatar-fallback">--</span><span>No public player list available.</span></li>`;
    return;
  }

  dom.playerList.innerHTML = safePlayers
    .map((player) => {
      const safeName = escapeHtml(player.name);
      const headSrc = `https://mc-heads.net/avatar/${encodeURIComponent(player.name)}/32`;
      return `
        <li>
          <img
            class="player-avatar"
            src="${headSrc}"
            alt="${safeName} Minecraft head"
            width="32"
            height="32"
            loading="lazy"
            decoding="async"
            referrerpolicy="no-referrer"
            onerror="this.replaceWith(Object.assign(document.createElement('span'), { className: 'player-avatar player-avatar-fallback', textContent: '${escapeJsString(
              getInitials(player.name)
            )}' }))"
          >
          <span>${safeName}</span>
        </li>`;
    })
    .join("");
}

function escapeJsString(value) {
  return String(value)
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/\r/g, "\\r")
    .replace(/\n/g, "\\n");
}

function setServerChip(status, label) {
  if (!dom.serverChip || !dom.chipText) return;

  dom.serverChip.classList.remove("online", "offline");
  if (status === "online" || status === "offline") {
    dom.serverChip.classList.add(status);
  }
  dom.chipText.textContent = label;
}

function initCityCanvas() {
  const canvas = dom.cityCanvas;
  if (!canvas) return;

  const context = canvas.getContext("2d");
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const buildings = createBuildings(90);

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function draw(time = 0) {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#080a0f";
    context.fillRect(0, 0, width, height);

    drawSky(context, width, height, time);
    drawBuildings(context, buildings, width, height, time);
    drawCircuitRoad(context, width, height, time);

    if (!prefersReducedMotion) {
      state.cityAnimationId = window.requestAnimationFrame(draw);
    }
  }

  resize();
  draw();
  window.addEventListener("resize", () => {
    resize();
    draw();
  });
}

function createBuildings(count) {
  return Array.from({ length: count }, (_, index) => {
    const lane = index % 3;
    return {
      x: Math.random(),
      height: 0.18 + Math.random() * (lane === 0 ? 0.32 : 0.48),
      width: 18 + Math.random() * 42,
      lane,
      hue: index % 5,
      windowSeed: Math.random() * 100,
    };
  });
}

function drawSky(context, width, height, time) {
  const pulse = Math.sin(time / 900) * 0.12 + 0.78;
  context.save();
  context.globalAlpha = pulse;
  context.strokeStyle = "rgba(67, 232, 255, 0.18)";
  context.lineWidth = 1;

  for (let y = 80; y < height * 0.7; y += 44) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y - 18);
    context.stroke();
  }

  context.restore();
}

function drawBuildings(context, buildings, width, height, time) {
  const horizon = height * 0.72;
  const colors = ["#123347", "#321a42", "#1d2840", "#3b2032", "#152f2a"];

  buildings.forEach((building, index) => {
    const drift = ((time / (36000 + building.lane * 8000) + building.x) % 1) * width;
    const x = width - drift - building.width;
    const laneOffset = building.lane * 46;
    const buildingHeight = height * building.height;
    const y = horizon - buildingHeight + laneOffset;

    context.fillStyle = colors[building.hue];
    context.fillRect(x, y, building.width, buildingHeight);
    context.strokeStyle = "rgba(149, 247, 255, 0.18)";
    context.strokeRect(x + 0.5, y + 0.5, building.width, buildingHeight);

    drawWindows(context, x, y, building.width, buildingHeight, index + building.windowSeed);
  });
}

function drawWindows(context, x, y, width, height, seed) {
  const windowSize = 4;
  const gap = 8;
  const palettes = ["#43e8ff", "#ff3fd1", "#ffcf5a", "#54ff9b"];

  for (let row = y + 10; row < y + height - 8; row += gap) {
    for (let col = x + 8; col < x + width - 6; col += gap) {
      const lit = Math.sin(row * 0.17 + col * 0.11 + seed) > 0.28;
      if (!lit) continue;

      context.fillStyle = palettes[Math.abs(Math.floor(row + col + seed)) % palettes.length];
      context.globalAlpha = 0.72;
      context.fillRect(col, row, windowSize, windowSize);
      context.globalAlpha = 1;
    }
  }
}

function drawCircuitRoad(context, width, height, time) {
  const floorTop = height * 0.74;
  context.save();
  context.fillStyle = "#06080d";
  context.fillRect(0, floorTop, width, height - floorTop);

  context.strokeStyle = "rgba(67, 232, 255, 0.38)";
  context.lineWidth = 1;

  for (let i = 0; i < 18; i += 1) {
    const y = floorTop + i * 22 + ((time / 40) % 22);
    context.beginPath();
    context.moveTo(width * 0.42 - i * 28, y);
    context.lineTo(width * 0.68 + i * 34, y);
    context.stroke();
  }

  for (let i = 0; i < 12; i += 1) {
    const offset = i * 80 + ((time / 22) % 80);
    context.strokeStyle = i % 2 ? "rgba(255, 63, 209, 0.45)" : "rgba(255, 207, 90, 0.45)";
    context.beginPath();
    context.moveTo(width * 0.5 + offset, floorTop);
    context.lineTo(width * 0.3 + offset * 0.35, height);
    context.stroke();
  }

  context.restore();
}

function setText(node, value) {
  if (node) node.textContent = value;
}

function titleCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatTime(date) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getInitials(name) {
  return name
    .split(/[^a-z0-9]+/i)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
