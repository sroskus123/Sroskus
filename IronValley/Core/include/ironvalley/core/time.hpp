// Cas v jadre pravidel: cele mikrosekundy. Stejna semantika jako Web/src/core/time.js.
#pragma once

#include <cmath>
#include <cstdint>

namespace iv::core {

using Micros = std::int64_t;

constexpr Micros kMicrosPerSecond = 1000000;

/// Nejvetsi platne dt jednoho volani: 2^53 - 1 us (JS Number.MAX_SAFE_INTEGER). Vetsi nebo zaporne dt je chyba
/// volajiciho (JS vyhodi RangeError, C++ tik neprovede). Mezisoucty jadra tak nikdy nepretecou int64.
constexpr Micros kMaxDtUs = 9007199254740991LL;

/// Je dt platne cele cislo mikrosekund pro jadro (0 <= dt <= kMaxDtUs)?
constexpr bool validDt(Micros dtUs) { return dtUs >= 0 && dtUs <= kMaxDtUs; }

/// Prevod sekund na cele mikrosekundy se stejnym zaokrouhlenim jako JS Math.round (polovina smerem k +nekonecnu).
/// Predpoklad: seconds * 10^6 lezi v rozsahu int64, jinak je vysledek std::llround nespecifikovany. Volajici hodnotu
/// kontroluje predem (rulesFromJson: kazdy cas je omezeny rozsahem a kadence >= 1 rana/min, Docs/RULES.md oddil 2).
inline Micros secondsToMicros(double seconds) {
  const double x = seconds * 1e6;
  Micros r = static_cast<Micros>(std::llround(x));  // polovina od nuly
  if (x < 0.0 && static_cast<double>(r) - x == -0.5) r += 1;
  return r;
}

/// Prevod plovouciho casu enginu na cele mikrosekundy bez kumulace zaokrouhlovaci chyby.
class TickClock {
 public:
  /// dtSeconds musi byt >= 0; zaporna hodnota se ignoruje (vrati 0).
  Micros advance(double dtSeconds) {
    if (!(dtSeconds >= 0.0)) return 0;
    totalSeconds_ += dtSeconds;
    const Micros now = secondsToMicros(totalSeconds_);
    const Micros dt = now - lastMicros_;
    lastMicros_ = now;
    return dt;
  }

 private:
  double totalSeconds_ = 0.0;
  Micros lastMicros_ = 0;
};

}  // namespace iv::core
