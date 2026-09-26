// Cas v jadre pravidel: cele mikrosekundy (integer). Viz Docs/RULES.md, oddil "Cas".
// Duvod: soucet libovolneho rozdeleni stejneho intervalu na tiky je presny, takze vysledek
// (pocet vystrelu, body, konec kola) nezavisi na delce snimku a JS i C++ dava bit po bitu totez.

export const MICROS_PER_SECOND = 1000000;

/** Prevede sekundy (konfigurace) na cele mikrosekundy. Zaokrouhleni: nejblizsi, polovina nahoru. */
export function secondsToMicros(seconds) {
  return Math.round(seconds * MICROS_PER_SECOND);
}

/**
 * Prevod plovouciho casu enginu na cele mikrosekundy bez kumulace zaokrouhlovaci chyby.
 * Engine vola advance(dtSeconds) kazdy krok a dostane celociselne dt pro jadro.
 */
export class TickClock {
  constructor() {
    this.totalSeconds = 0;
    this.lastMicros = 0;
  }

  advance(dtSeconds) {
    if (!(dtSeconds >= 0)) throw new RangeError('TickClock.advance: dt musi byt >= 0');
    this.totalSeconds += dtSeconds;
    const now = secondsToMicros(this.totalSeconds);
    const dt = now - this.lastMicros;
    this.lastMicros = now;
    return dt;
  }
}

/** Kontrola vstupniho dt pro jadro: cele nezaporne cislo mikrosekund. */
export function assertDtMicros(dtUs) {
  if (!Number.isSafeInteger(dtUs) || dtUs < 0) {
    throw new RangeError(`dt musi byt cele nezaporne cislo mikrosekund, dostal jsem ${dtUs}`);
  }
}
