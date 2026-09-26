// IRON VALLEY — AI system STUB (herní integrace).
//
// Tento soubor je jen zástupný stub se závaznou signaturou z Docs/GAMEPLAY_CONTRACTS.md.
// Nic nedělá. AI agent ho nahradí skutečnou implementací se STEJNÝM rozhraním.
//
// createAISystem({ combatants, world, nav, cover, events, match, config }) → {
//   addBot(combatant), removeBot(id), update(dt), getDebug(), reset()
// }

export function createAISystem({ combatants, world, nav, cover, events, match, config } = {}) {
  const bots = new Map();
  return {
    isStub: true,
    addBot(combatant) {
      if (combatant && combatant.id != null) bots.set(combatant.id, combatant);
    },
    removeBot(id) {
      bots.delete(id);
    },
    update(dt) {
      // no-op: boti v stubu stojí (cmd se neposílá).
    },
    getDebug() {
      return { stub: true, bots: [...bots.keys()] };
    },
    reset() {
      // no-op
    },
  };
}
