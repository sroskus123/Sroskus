// Cas v jadre pravidel: cele mikrosekundy. Stejna semantika jako Web/src/core/time.js.
#pragma once

#include <cmath>
#include <cstdint>

namespace iv::core {

using Micros = std::int64_t;

constexpr Micros kMicrosPerSecond = 1000000;

/// Prevod sekund na cele mikrosekundy se stejnym zaokrouhlenim jako JS Math.round (polovina smerem k +nekonecnu).
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
