# Cybercraft2069 Static Frontend

Cybercraft2069 is a static HTML/CSS/JS site for a cyberpunk Minecraft MMO modded multiplayer server set in Linefield City.

## Files

- `index.html` contains the page structure and hash-routed sections.
- `styles.css` contains the full responsive visual system.
- `script.js` contains navigation, copy-IP behavior, server-status fetching, player-list rendering, and the animated canvas city.
- `assets/` contains generated Minecraft-style job card backgrounds.

## Configure Server Status

Open `script.js` and update:

```js
const SERVER_CONFIG = {
  host: "144.76.87.106:25658",
  statusApiBase: "https://api.mcsrvstat.us/3/",
  refreshMs: 60_000,
};
```

Use a Java server hostname or `hostname:port`. The frontend uses the public mcsrvstat.us v3 endpoint and falls back to demo data if the configured host cannot be reached.

## External Links

- Server: `144.76.87.106:25658`
- BlueMap: <http://144.76.87.106:25643/#world:2332:0:847:2250:0:0:0:0:perspective>
- CurseForge: <https://www.curseforge.com/minecraft/modpacks/cybercraft2069>
- Modrinth: <https://modrinth.com/modpack/cybercraft2069>
- MCBlox: <https://www.mcblox.online/game.html?id=b5936211-f181-4173-a694-b334e3660418>
- Trailer: <https://www.youtube.com/watch?v=50xNXWvCduQ>

## Configure Content

- The Ranks page in `index.html` contains the current Adventurer/Hero/Legend donation reward tiers and policy notice.
- Home page includes a `Play Cybercraft2069` modal with launcher links (CurseForge, Modrinth, MCBlox) and trailer.
- Edit the Jobs page in `index.html` if the CurseForge description changes.
- Keep unconfirmed systems and perks out of the public page until the server team confirms them.
- Video embeds are in the `Media` page in `index.html`.

## Run

Open `index.html` directly in a browser. No build step or server is required.
