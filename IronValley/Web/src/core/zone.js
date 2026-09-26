// Bodovani kontrolni oblasti. Pravidla: Docs/RULES.md, oddil "Kontrolni oblast". C++: Core/src/zone.cpp.

import { assertDtMicros } from './time.js';

/**
 * Normalizuje ucastnika z objektu {id, team, alive, active, inZone} nebo pole [id, team, alive, active, inZone].
 */
export function normalizeParticipant(p) {
  if (Array.isArray(p)) return { id: p[0], team: p[1], alive: p[2] === true, active: p[3] === true, inZone: p[4] === true };
  return { id: p.id, team: p.team, alive: p.alive === true, active: p.active === true, inZone: p.inZone === true };
}

/** Kontrola vstupu tiku. Vraci 'ok' | 'invalid_id' | 'invalid_team' | 'duplicate_id'. */
export function validateParticipants(participants, teamCount) {
  if (!Array.isArray(participants)) return 'invalid_id';
  const seen = new Set();
  for (const raw of participants) {
    const p = normalizeParticipant(raw);
    if (typeof p.id !== 'string' || p.id.length === 0) return 'invalid_id';
    if (!Number.isInteger(p.team) || p.team < 0 || p.team >= teamCount) return 'invalid_team';
    if (seen.has(p.id)) return 'duplicate_id';
    seen.add(p.id);
  }
  return 'ok';
}

/** Celociselne deleni nezapornych celych cisel (presne i pro velka cisla v double). */
export function intDiv(a, b) {
  let q = Math.floor(a / b);
  if (q * b > a) q -= 1;
  else if ((q + 1) * b <= a) q += 1;
  return q;
}

export class ZoneScoring {
  /**
   * @param rules zkompilovana pravidla (teamCount, zone.pointIntervalUs, zone.pointsPerAward)
   */
  constructor(rules) {
    this.teamCount = rules.teamCount;
    this.pointIntervalUs = rules.zone.pointIntervalUs;
    this.pointsPerAward = rules.zone.pointsPerAward;
    this.reset();
  }

  reset() {
    this.scores = new Array(this.teamCount).fill(0);
    this.counts = new Array(this.teamCount).fill(0);
    this.status = 'empty';
    this.controller = -1;
    this.progressUs = 0;
  }

  /**
   * Urci stav oblasti ze seznamu ucastniku. Pocitaji se jen alive && active && inZone.
   * Zmena kontrolora (vcetne na "nikdo") vynuluje rozpracovany postup.
   */
  evaluate(participants) {
    const err = validateParticipants(participants, this.teamCount);
    if (err !== 'ok') return err;
    const counts = new Array(this.teamCount).fill(0);
    for (const raw of participants) {
      const p = normalizeParticipant(raw);
      if (p.alive && p.active && p.inZone) counts[p.team] += 1;
    }
    let best = 0;
    let bestTeam = -1;
    let tie = false;
    for (let t = 0; t < this.teamCount; t += 1) {
      if (counts[t] > best) {
        best = counts[t];
        bestTeam = t;
        tie = false;
      } else if (counts[t] === best && best > 0) {
        tie = true;
      }
    }
    let status;
    let controller;
    if (best === 0) {
      status = 'empty';
      controller = -1;
    } else if (tie) {
      status = 'contested';
      controller = -1;
    } else {
      status = 'controlled';
      controller = bestTeam;
    }
    if (controller !== this.controller || controller === -1) this.progressUs = 0;
    this.counts = counts;
    this.status = status;
    this.controller = controller;
    return 'ok';
  }

  /**
   * Nechá plynout dtUs platne kontroly aktualniho kontrolora. maxAwards omezi pocet udelenych bodovych kroku
   * (kolo konci pri dosazeni cile). Vraci {awards, usedUs}: usedUs = cas do posledniho udeleni, pokud se narazilo na limit.
   */
  advance(dtUs, maxAwards = Number.POSITIVE_INFINITY) {
    assertDtMicros(dtUs);
    if (!(maxAwards >= 1)) throw new RangeError('ZoneScoring.advance: maxAwards musi byt >= 1');
    if (this.controller === -1) {
      this.progressUs = 0;
      return { awards: 0, usedUs: dtUs };
    }
    const total = this.progressUs + dtUs;
    let awards = intDiv(total, this.pointIntervalUs);
    if (awards >= maxAwards) {
      awards = maxAwards;
      const usedUs = awards * this.pointIntervalUs - this.progressUs;
      this.scores[this.controller] += awards * this.pointsPerAward;
      this.progressUs = 0;
      return { awards, usedUs };
    }
    this.scores[this.controller] += awards * this.pointsPerAward;
    this.progressUs = total - awards * this.pointIntervalUs;
    return { awards, usedUs: dtUs };
  }

  /** Samostatny tik oblasti: evaluate + advance. Vraci 'ok' nebo kod chyby (stav se pri chybe nemeni). */
  tick(dtUs, participants) {
    assertDtMicros(dtUs);
    const err = this.evaluate(participants);
    if (err !== 'ok') return err;
    this.advance(dtUs);
    return 'ok';
  }

  snapshot() {
    return {
      status: this.status,
      controller: this.controller,
      counts: this.counts.slice(),
      progressUs: this.progressUs,
      scores: this.scores.slice(),
    };
  }
}
