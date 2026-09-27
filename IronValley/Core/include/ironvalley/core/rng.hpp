// Deterministicky generator mulberry32. Bit po bitu shodny s Web/src/core/rng.js (overuje Shared/testvectors/rng.json).
#pragma once

#include <cstdint>
#include <vector>

namespace iv::core {

class Rng {
 public:
  explicit Rng(std::uint32_t seed) : state_(seed) {}

  std::uint32_t nextU32() {
    state_ += 0x6D2B79F5u;
    std::uint32_t t = state_;
    t = (t ^ (t >> 15)) * (t | 1u);
    t ^= t + (t ^ (t >> 7)) * (t | 61u);
    return t ^ (t >> 14);
  }

  /// Index v [0, n) = floor(u32 * n / 2^32). n musi byt >= 1 (pro n == 0 vraci 0 bez spotreby cisla).
  std::uint32_t pickIndex(std::uint32_t n) {
    if (n == 0) return 0;
    return static_cast<std::uint32_t>((static_cast<std::uint64_t>(nextU32()) * n) >> 32);
  }

  /// Fisher-Yates od konce: permutace 0..n-1.
  std::vector<int> shuffledIndices(int n) {
    std::vector<int> out;
    out.reserve(n > 0 ? static_cast<std::size_t>(n) : 0u);
    for (int i = 0; i < n; ++i) out.push_back(i);
    for (int i = n - 1; i >= 1; --i) {
      const int j = static_cast<int>(pickIndex(static_cast<std::uint32_t>(i + 1)));
      const int tmp = out[static_cast<std::size_t>(i)];
      out[static_cast<std::size_t>(i)] = out[static_cast<std::size_t>(j)];
      out[static_cast<std::size_t>(j)] = tmp;
    }
    return out;
  }

  std::uint32_t state() const { return state_; }

 private:
  std::uint32_t state_;
};

constexpr std::uint32_t kSpawnSeedSalt = 0x9E3779B9u;

inline std::uint32_t deriveSeed(std::uint32_t seed, std::uint32_t salt) { return seed ^ salt; }

}  // namespace iv::core
