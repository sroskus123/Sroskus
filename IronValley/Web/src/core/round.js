// Stavovy automat kola: pre_round -> running -> ended (-> reset -> pre_round).
// Pravidla: Docs/RULES.md, oddil "Kolo". C++: Core/src/round.cpp.

import { assertDtMicros } from './time.js';
import { Rng } from './rng.js';
import { ZoneScoring, validateParticipants, intDiv } from './zone.js';

export class Round {
  /**
   * @param rules zkompilovana pravidla
   * @param seed semeno pro vyber aktivni oblasti (kazde kolo bere dalsi cislo ze stejne posloupnosti)
   */
  constructor(rules, seed = 1) {
    this.rules = rules;
    this.seed = seed >>> 0;
    this.rng = new Rng(this.seed);
    this.zone = new ZoneScoring(rules);
    this.roundNumber = 0;
    this.beginRound();
  }

  beginRound() {
    this.roundNumber += 1;
    this.zoneIndex = this.rng.pickIndex(this.rules.zone.locations.length);
    this.state = 'pre_round';
    this.preRoundRemainingUs = this.rules.round.preRoundUs;
    this.elapsedUs = 0;
    this.winner = -1;
    this.draw = false;
    this.endReason = 'none';
    this.zone.reset();
  }

  get zoneId() {
    return this.rules.zone.locations[this.zoneIndex].id;
  }

  get remainingUs() {
    return this.rules.round.timeLimitUs - this.elapsedUs;
  }

  get scores() {
    return this.zone.scores.slice();
  }

  /** Nove kolo: vynuluje skore, postup oblasti, casovace a vysledek; vybere dalsi oblast. */
  reset() {
    this.beginRound();
    return 'ok';
  }

  /** Okamzity start (preskoci zbytek odpoctu). */
  start() {
    if (this.state !== 'pre_round') return 'rejected';
    this.preRoundRemainingUs = 0;
    this.state = 'running';
    return 'ok';
  }

  /** Tik kola. participants: [{id, team, alive, active, inZone}]. Vraci 'ok' nebo kod chyby vstupu. */
  tick(dtUs, participants) {
    assertDtMicros(dtUs);
    const err = validateParticipants(participants, this.rules.teamCount);
    if (err !== 'ok') return err;
    if (this.state === 'ended') return 'ok';
    let remaining = dtUs;
    if (this.state === 'pre_round') {
      const use = Math.min(remaining, this.preRoundRemainingUs);
      this.preRoundRemainingUs -= use;
      remaining -= use;
      if (this.preRoundRemainingUs > 0) return 'ok';
      this.state = 'running';
    }
    this.zone.evaluate(participants);
    const { timeLimitUs, scoreTarget } = this.rules.round;
    const use = Math.min(remaining, timeLimitUs - this.elapsedUs);
    const c = this.zone.controller;
    let maxAwards = Number.POSITIVE_INFINITY;
    if (c >= 0) {
      const need = scoreTarget - this.zone.scores[c];
      const ppa = this.rules.zone.pointsPerAward;
      maxAwards = intDiv(need + ppa - 1, ppa);
    }
    const res = this.zone.advance(use, maxAwards);
    this.elapsedUs += res.usedUs;
    if (c >= 0 && this.zone.scores[c] >= scoreTarget) {
      this.finish('score_target', c, false);
    } else if (this.elapsedUs >= timeLimitUs) {
      this.finishByTime();
    }
    return 'ok';
  }

  finishByTime() {
    const s = this.zone.scores;
    let best = -1;
    let bestTeam = -1;
    let count = 0;
    for (let t = 0; t < s.length; t += 1) {
      if (s[t] > best) {
        best = s[t];
        bestTeam = t;
        count = 1;
      } else if (s[t] === best) {
        count += 1;
      }
    }
    if (count === 1) this.finish('time_limit', bestTeam, false);
    else this.finish('time_limit', -1, true);
  }

  finish(reason, winner, draw) {
    this.state = 'ended';
    this.endReason = reason;
    this.winner = winner;
    this.draw = draw;
    this.zone.progressUs = 0;
  }

  snapshot() {
    const z = this.zone.snapshot();
    return {
      state: this.state,
      roundNumber: this.roundNumber,
      zoneIndex: this.zoneIndex,
      zoneId: this.zoneId,
      preRoundRemainingUs: this.preRoundRemainingUs,
      elapsedUs: this.elapsedUs,
      remainingUs: this.remainingUs,
      winner: this.winner,
      draw: this.draw,
      endReason: this.endReason,
      status: z.status,
      controller: z.controller,
      counts: z.counts,
      progressUs: z.progressUs,
      scores: z.scores,
    };
  }
}
