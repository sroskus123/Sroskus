// C++ specificke testy jadra (doplnek ke sdilenym vektorum): zaokrouhleni casu shodne s JS, TickClock,
// hodnoty v rules.json, pritomnost souboru vektoru, vlastnosti kadence a invariant munice na strane C++.
//
// Pouziti: ivcore_unit <cesta k adresari Shared>

#include <cstdio>
#include <fstream>
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "ironvalley/core/core.hpp"
#include "ironvalley/core/rules_json.hpp"

using nlohmann::json;
using namespace iv::core;

namespace {

int g_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& what) {
  ++g_checks;
  if (!ok) {
    ++g_failures;
    std::cout << "FAIL " << what << "\n";
  }
}

json loadJson(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  std::stringstream ss;
  ss << in.rdbuf();
  return json::parse(ss.str());
}

bool fileExists(const std::string& path) { return std::ifstream(path).good(); }

std::vector<Micros> hzTicks(Micros duration, long long hz) {
  std::vector<Micros> out;
  Micros prev = 0;
  for (long long k = 1; prev < duration; ++k) {
    Micros t = (2 * k * 1000000 + hz) / (2 * hz);
    if (t > duration) t = duration;
    out.push_back(t - prev);
    prev = t;
  }
  return out;
}

std::vector<Micros> randomTicks(Rng& rng, Micros duration, std::uint32_t maxUs) {
  std::vector<Micros> out;
  Micros t = 0;
  while (t < duration) {
    const Micros dt = std::min<Micros>(rng.pickIndex(maxUs + 1), duration - t);
    out.push_back(dt);
    t += dt;
  }
  return out;
}

struct ScenarioResult {
  std::vector<Micros> shots;
  int magazine, chamber, reserve, shotsFired;
  Micros clock, cooldown;
  bool invariantOk = true;
  bool operator==(const ScenarioResult& o) const {
    return shots == o.shots && magazine == o.magazine && chamber == o.chamber && reserve == o.reserve &&
           shotsFired == o.shotsFired && clock == o.clock && cooldown == o.cooldown && invariantOk && o.invariantOk;
  }
};

ScenarioResult runScenario(const WeaponDef& def, const std::function<std::vector<Micros>(Micros)>& partition) {
  WeaponState w(def);
  ScenarioResult r{};
  struct Seg {
    Micros us;
    bool trigger;
    int after;  // 0 nic, 1 reload, 2 interrupt
  };
  const std::vector<Seg> segs = {{2500000, true, 0}, {500000, false, 1}, {3500000, true, 0}, {100000, false, 0},
                                 {1000000, true, 1}, {700000, false, 2}, {2000000, true, 0}};
  for (const Seg& s : segs) {
    for (Micros dt : partition(s.us)) {
      w.update(dt, s.trigger);
      for (const WeaponEvent& e : w.takeEvents())
        if (e.type == WeaponEventType::Shot) r.shots.push_back(e.atUs);
      if (!w.invariantViolations().empty()) r.invariantOk = false;
    }
    if (s.after == 1) w.reload();
    if (s.after == 2) w.interrupt(InterruptReason::Sprint);
    w.takeEvents();
  }
  r.magazine = w.magazine();
  r.chamber = w.chamber();
  r.reserve = w.reserve();
  r.shotsFired = w.shotsFired();
  r.clock = w.clockUs();
  r.cooldown = w.cooldownUs();
  return r;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "pouziti: ivcore_unit <adresar Shared>\n";
    return 2;
  }
  const std::string shared = argv[1];

  // --- zaokrouhleni sekund na mikrosekundy (musi odpovidat JS Math.round) ---
  check(secondsToMicros(60.0 / 750.0) == 80000, "60/750 s = 80000 us");
  check(secondsToMicros(60.0 / 450.0) == 133333, "60/450 s = 133333 us");
  check(secondsToMicros(60.0 / 700.0) == 85714, "60/700 s = 85714 us");
  check(secondsToMicros(1.0000005) == 1000001, "polovina nahoru");
  check(secondsToMicros(2.35) == 2350000, "2.35 s");
  check(secondsToMicros(-0.0000005) == 0, "zaporna polovina k +nekonecnu (JS Math.round)");
  check(secondsToMicros(-0.0000015) == -1, "zaporna polovina k +nekonecnu (JS Math.round) 2");

  // --- TickClock bez driftu ---
  {
    TickClock clock;
    Micros sum = 0;
    for (int i = 0; i < 144 * 600; ++i) sum += clock.advance(1.0 / 144.0);
    check(sum >= 600000000 - 1 && sum <= 600000000 + 1, "TickClock 1/144 s x 600 s bez driftu");
    TickClock c2;
    Micros s2 = 0;
    for (int i = 0; i < 60; ++i) s2 += c2.advance(1.0 / 60.0);
    check(s2 == 1000000, "TickClock 60 x 1/60 s = 1 s");
    check(c2.advance(-1.0) == 0, "TickClock ignoruje zaporne dt");
  }

  // --- rules.json: hodnoty ze zadani ---
  Rules rules;
  {
    std::vector<std::string> errors;
    const bool ok = rulesFromJson(loadJson(shared + "/config/rules.json"), rules, errors);
    check(ok, "rules.json je platny" + (errors.empty() ? std::string() : ": " + errors.front()));
    check(rules.teamCount == 3 && rules.teamSize == 6, "3 tymy po 6");
    check(rules.round.timeLimitUs == 600000000 && rules.round.scoreTarget == 100, "kolo 600 s, cil 100");
    check(rules.zone.pointIntervalUs == 2000000 && rules.zone.pointsPerAward == 1, "1 bod / 2 s");
    check(rules.zone.locations.size() == 3, "tri umisteni oblasti");
    check(rules.respawn.delayUs == 5000000, "respawn 5 s");
    check(!rules.combat.friendlyFire, "friendly fire vypnuty");
    const WeaponDef* rifle = rules.findWeapon("rifle_iv7");
    const WeaponDef* pistol = rules.findWeapon("pistol_p9");
    check(rifle && rifle->magazineCapacity == 30 && rifle->hasChamber, "puska 30+1");
    check(pistol && pistol->magazineCapacity == 15 && pistol->hasChamber, "pistole 15+1");
    check(validateRules(rules).empty(), "validateRules(rules.json) bez chyb");
    check(!validateRules(Rules{}).empty(), "validateRules odmitne prazdna pravidla");
  }

  // --- vsechny sdilene soubory vektoru existuji ---
  for (const char* name : {"weapon", "zone", "round", "respawn", "match", "rules", "rng", "fuzz_weapon", "fuzz_zone",
                           "fuzz_round", "fuzz_respawn", "fuzz_match"}) {
    check(fileExists(shared + "/testvectors/" + name + ".json"), std::string("existuje testvectors/") + name + ".json");
  }

  // --- kadence nezavisla na delce tiku (C++ strana, 200 nahodnych rozdeleni) ---
  if (const WeaponDef* rifle = rules.findWeapon("rifle_iv7")) {
    const ScenarioResult ref = runScenario(*rifle, [](Micros us) { return hzTicks(us, 60); });
    check(ref.shots.size() > 40, "scenar kadence vystreli dost ran");
    for (long long hz : {30LL, 144LL, 240LL, 7LL})
      check(runScenario(*rifle, [hz](Micros us) { return hzTicks(us, hz); }) == ref, "kadence @" + std::to_string(hz) + " Hz");
    Rng rng(0xabcdefu);
    for (int i = 0; i < 200; ++i) {
      const std::uint32_t maxUs = std::vector<std::uint32_t>{1000, 20000, 100000, 1500000}[static_cast<std::size_t>(i % 4)];
      check(runScenario(*rifle, [&](Micros us) { return randomTicks(rng, us, maxUs); }) == ref,
            "kadence nahodne rozdeleni #" + std::to_string(i));
    }
  }

  // --- invariant munice pri 300 nahodnych posloupnostech ---
  {
    Rng rng(20260926u);
    const char* ids[] = {"rifle_iv7", "pistol_p9"};
    for (int run = 0; run < 300; ++run) {
      const WeaponDef* def = rules.findWeapon(ids[run % 2]);
      if (def == nullptr) break;
      WeaponState w(*def);
      w.setAmmo(static_cast<int>(rng.pickIndex(static_cast<std::uint32_t>(def->magazineCapacity + 1))),
                static_cast<int>(rng.pickIndex(2)), static_cast<int>(rng.pickIndex(60)));
      bool trigger = false;
      bool ok = true;
      for (int i = 0; i < 200; ++i) {
        const std::uint32_t x = rng.pickIndex(100);
        if (x < 55) {
          if (rng.pickIndex(4) == 0) trigger = !trigger;
          w.update(rng.pickIndex(400000), trigger);
        } else if (x < 70) {
          w.reload();
        } else if (x < 82) {
          w.interrupt(static_cast<InterruptReason>(rng.pickIndex(3)));
        } else if (x < 88) {
          w.resupply(rng.pickIndex(40));
        } else if (x < 90) {
          w.resetToLoadout();
        } else {
          w.setFireMode(def->fireModes[rng.pickIndex(static_cast<std::uint32_t>(def->fireModes.size()))]);
        }
        if (!w.invariantViolations().empty()) ok = false;
      }
      check(ok, "invariant munice, beh " + std::to_string(run));
    }
  }

  // --- neplatna konfigurace spawnu se ohlasi bez vyjimky ---
  {
    RespawnSystem bad(rules, 1, {{Vec3{}}, {}});
    check(!bad.configError().empty(), "RespawnSystem hlasi chybejici spawnove oblasti");
    check(bad.addParticipant("a1", 0) != AddResult::Ok, "RespawnSystem s chybnou konfiguraci odmita ucastniky");
  }

  // --- WeaponState* z RespawnSystem::weapon() plati po celou dobu zivota systemu (Docs/RULES.md, oddil 5) ---
  // Bez stabilnich objektu by cteni/zapis pres ukazatel po respawnu nebo resetu byl use-after-free (odhali build
  // s -DIV_SANITIZE=ON, i kdyby hodnota nahodou sedela).
  {
    const std::vector<std::vector<Vec3>> areas = {{Vec3{0, 0, 0}}, {Vec3{100, 0, 0}}, {Vec3{0, 0, 100}}};
    Match m(rules, 3, areas);
    m.addParticipant("a1", 0);
    const MatchWorld world;
    m.update(0, world);
    WeaponState* w = m.respawn().weapon("a1", "rifle_iv7");
    WeaponState* p = m.respawn().weapon("a1", "pistol_p9");
    check(w != nullptr && p != nullptr, "ukazatele na vybavene zbrane");
    if (w != nullptr && p != nullptr) {
      check(w->update(16667, true) == 1 && w->magazine() == 29, "vystrel pres ukazatel");
      m.kill("a1");
      check(!w->enabled() && !p->enabled(), "zbrane mrtveho ucastnika jsou vypnute");
      check(w->update(1000000, true) == 0 && w->reload() == ReloadResult::RejectedDisabled, "mrtvy nestrili ani neprebiji");
      m.update(5000000, world);
      check(m.respawn().weapon("a1", "rifle_iv7") == w, "po respawnu stejny objekt");
      check(w->magazine() == 30 && w->enabled(), "po respawnu reset na miste a zapnuto");
      check(w->update(100000, true) == 0, "spoust drzena pres smrt a respawn nevystreli");
      w->update(16667, false);
      check(w->update(16667, true) == 1 && w->magazine() == 29, "zapis pres stary ukazatel po respawnu");
      m.reset();
      check(m.respawn().weapon("a1", "rifle_iv7") == w && w->magazine() == 30 && !w->enabled(),
            "reset kola: stejny objekt, plny, vypnuty do spawnu");
      for (int i = 0; i < 17; ++i) m.addParticipant("x" + std::to_string(i), 1 + i % 2);  // vektor ucastniku se realokuje
      m.update(0, world);
      check(m.respawn().weapon("a1", "rifle_iv7") == w && w->enabled(), "pridani ucastniku: stejny objekt");
      const std::vector<std::string> pistolOnly = {"pistol_p9"};
      m.respawn().setLoadout("a1", pistolOnly);
      m.kill("a1");
      m.update(5000000, world);
      check(m.respawn().weapon("a1", "rifle_iv7") == nullptr, "odebrana puska neni vybavena");
      check(m.respawn().weapon("a1", "pistol_p9") == p && p->enabled(), "pistole je porad stejny objekt");
      w->update(16667, false);
      check(!w->enabled() && w->update(100000, true) == 0 && w->reload() == ReloadResult::RejectedDisabled,
            "stary ukazatel na odebranou pusku je platny a vypnuty");
      m.respawn().setLoadout("a1", rules.defaultLoadout);
      m.kill("a1");
      m.update(5000000, world);
      check(m.respawn().weapon("a1", "rifle_iv7") == w && w->enabled() && w->magazine() == 30,
            "znovu vybavena puska je puvodni objekt");
    }
  }

  // --- zaporne dt je v C++ bez ucinku (JS vyhodi RangeError); Docs/RULES.md, oddil 1 ---
  {
    const std::vector<ZoneParticipant> teamA = {ZoneParticipant{"a1", 0, true, true, true}};
    const std::vector<ZoneParticipant> teamB = {ZoneParticipant{"b1", 1, true, true, true}};
    Round r(rules, 7);
    r.start();
    r.tick(1500000, teamA);
    auto roundState = [&r]() {
      return std::to_string(static_cast<int>(r.state())) + "/" + std::to_string(r.elapsedUs()) + "/" +
             std::to_string(r.zone().progressUs()) + "/" + std::to_string(r.zone().controller()) + "/" +
             std::to_string(static_cast<int>(r.zone().status())) + "/" + std::to_string(r.zone().scores()[0]) + "/" +
             std::to_string(r.zone().counts()[1]);
    };
    const std::string before = roundState();
    // Zmena kontrolora by pri vyhodnoceni vynulovala postup; zaporne dt nesmi vyhodnocovat vubec.
    check(r.tick(-1, teamB) == InputResult::InvalidDt && roundState() == before, "Round::tick(-1) nic nezmeni");

    ZoneScoring z(rules);
    z.tick(1500000, teamA);
    check(z.tick(-5, teamB) == InputResult::InvalidDt && z.progressUs() == 1500000 && z.controller() == 0,
          "ZoneScoring::tick(-5) nic nezmeni");
    const ZoneScoring::Advance a1 = z.advance(-5);
    const ZoneScoring::Advance a2 = z.advance(600000, 0);
    check(a1.awards == 0 && a1.usedUs == 0 && a2.awards == 0 && a2.usedUs == 0 && z.progressUs() == 1500000 &&
              z.scores()[0] == 0,
          "ZoneScoring::advance(-5) a advance(maxAwards 0) nic nezmeni");

    const std::vector<std::vector<Vec3>> areas = {{Vec3{0, 0, 0}}, {Vec3{100, 0, 0}}, {Vec3{0, 0, 100}}};
    RespawnSystem rs(rules, 1, areas);
    rs.addParticipant("a1", 0);
    rs.update(-1, SpawnPredicate());
    check(rs.participant("a1")->state == LifeState::Respawning && rs.takeEvents().empty(), "RespawnSystem::update(-1) nespawnuje");
    rs.update(0, SpawnPredicate());
    rs.kill("a1");
    rs.update(-1, SpawnPredicate());
    check(rs.participant("a1")->respawnInUs == rules.respawn.delayUs, "RespawnSystem::update(-1) neposune odpocet");

    Match m(rules, 3, areas);
    m.addParticipant("a1", 0);
    check(m.update(-1, MatchWorld()) == InputResult::InvalidDt &&
              m.respawn().participant("a1")->state == LifeState::Respawning &&
              m.round().preRoundRemainingUs() == rules.round.preRoundUs,
          "Match::update(-1) vrati InvalidDt a nic nezmeni");
    check(std::string(toString(InputResult::InvalidDt)) == "invalid_dt", "toString(InvalidDt)");
  }

  // --- V2-P2-4: trida vytvorena z neoverenych pravidel (vychozi Rules{}, chyba parseru enginu) nespadne ani
  //     nezamrzne; operace jsou bez ucinku a hlasi InvalidConfig ---
  {
    const std::vector<std::vector<Vec3>> areas = {{Vec3{0, 0, 0}}, {Vec3{100, 0, 0}}, {Vec3{0, 0, 100}}};
    const std::vector<ZoneParticipant> teamA = {ZoneParticipant{"a1", 0, true, true, true}};
    const Rules empty{};

    ZoneScoring z0(empty);
    check(!z0.configError().empty() && z0.tick(1000, teamA) == InputResult::InvalidConfig && z0.scores().empty(),
          "ZoneScoring(Rules{}): InvalidConfig bez deleni nulou");
    Rules interval0 = rules;
    interval0.zone.pointIntervalUs = 0;
    ZoneScoring z1(interval0);
    check(!z1.configError().empty() && z1.tick(1000, teamA) == InputResult::InvalidConfig &&
              z1.advance(1000).awards == 0 && z1.evaluate(teamA) == InputResult::InvalidConfig,
          "ZoneScoring s pointInterval 0: bez SIGFPE, InvalidConfig");
    Rules ppa0 = rules;
    ppa0.zone.pointsPerAward = 0;
    Round r0(ppa0, 1);
    check(!r0.configError().empty() && !r0.start() && r0.tick(5000000, teamA) == InputResult::InvalidConfig,
          "Round s pointsPerAward 0: bez SIGFPE, InvalidConfig");
    Round r1(empty, 1);
    check(!r1.configError().empty() && r1.zoneId().empty() && r1.tick(1000, {}) == InputResult::InvalidConfig,
          "Round(Rules{}): zadna oblast, zoneId prazdne (zadne cteni mimo pole)");

    Rules retry0 = rules;
    retry0.respawn.retryIntervalUs = 0;
    RespawnSystem rs0(retry0, 1, areas);
    check(!rs0.configError().empty() && rs0.addParticipant("a1", 0) == AddResult::InvalidConfig,
          "RespawnSystem s retryInterval 0: InvalidConfig");
    rs0.update(1000000, [](const SpawnQuery&) { return false; });  // drive nekonecna smycka
    check(rs0.participants().empty(), "RespawnSystem s retryInterval 0: update se vrati");
    Rules retryNeg = rules;
    retryNeg.respawn.retryIntervalUs = -5;
    RespawnSystem rs1(retryNeg, 1, areas);
    rs1.update(1000000, [](const SpawnQuery&) { return false; });
    check(!rs1.configError().empty(), "RespawnSystem se zapornym retryInterval: InvalidConfig, update se vrati");

    Match m0(empty, 1, areas);
    check(!m0.configError().empty() && m0.addParticipant("a1", 0) == AddResult::InvalidConfig && !m0.start() &&
              m0.update(1000000, MatchWorld()) == InputResult::InvalidConfig,
          "Match(Rules{}): InvalidConfig, zadna operace");
    check(std::string(toString(InputResult::InvalidConfig)) == "invalid_config" &&
              std::string(toString(AddResult::InvalidConfig)) == "invalid_config",
          "toString(InvalidConfig)");

    WeaponDef bad = *rules.findWeapon("rifle_iv7");
    bad.fireIntervalUs = 0;
    WeaponState wb(bad);
    check(!wb.configError().empty() && !wb.enabled() && wb.update(1000000, true) == 0 && wb.magazine() == 30 &&
              wb.clockUs() == 0 && wb.reload() == ReloadResult::RejectedDisabled && wb.resupply(10) == -1 &&
              !wb.setAmmo(1, 1, 1),
          "WeaponState s neplatnou definici je netecna");
    check(validateWeaponDef(*rules.findWeapon("rifle_iv7")).empty() && !validateWeaponDef(bad).empty(),
          "validateWeaponDef");
  }

  // --- dt nad 2^53 - 1 us je chyba volajiciho stejne jako v JS (Number.isSafeInteger) ---
  {
    const std::vector<ZoneParticipant> teamA = {ZoneParticipant{"a1", 0, true, true, true}};
    check(validDt(0) && validDt(kMaxDtUs) && !validDt(kMaxDtUs + 1) && !validDt(-1), "validDt");
    ZoneScoring z(rules);
    check(z.tick(kMaxDtUs + 1, teamA) == InputResult::InvalidDt && z.controller() == -1, "ZoneScoring: dt > 2^53-1");
    Round r(rules, 1);
    check(r.tick(kMaxDtUs + 1, teamA) == InputResult::InvalidDt && r.preRoundRemainingUs() == rules.round.preRoundUs,
          "Round: dt > 2^53-1");
    WeaponState w(*rules.findWeapon("rifle_iv7"));
    check(w.update(kMaxDtUs + 1, true) == 0 && w.clockUs() == 0 && w.magazine() == 30, "WeaponState: dt > 2^53-1");
    const std::vector<std::vector<Vec3>> areas = {{Vec3{0, 0, 0}}, {Vec3{100, 0, 0}}, {Vec3{0, 0, 100}}};
    Match m(rules, 1, areas);
    m.addParticipant("a1", 0);
    check(m.update(kMaxDtUs + 1, MatchWorld()) == InputResult::InvalidDt &&
              m.respawn().participant("a1")->state == LifeState::Respawning,
          "Match: dt > 2^53-1");
    // V2-P2-3: skore v int64, saturace na 2^53 - 1 misto preteceni int
    Rules big = rules;
    big.zone.pointIntervalUs = 1;
    big.zone.pointsPerAward = 1000;
    ZoneScoring zb(big);
    zb.tick(3000000, teamA);
    check(zb.scores()[0] == 3000000000LL, "skore 3e9 bez preteceni");
    zb.tick(kMaxDtUs, teamA);
    check(zb.scores()[0] == ZoneScoring::kMaxScore, "skore se zastavi na 2^53 - 1");
  }

  // --- V2-P1-1: zamek zivota nejde verejnym API odebrat; zamky enginu jsou nezavisle ---
  {
    const std::vector<std::vector<Vec3>> areas = {{Vec3{0, 0, 0}}, {Vec3{100, 0, 0}}, {Vec3{0, 0, 100}}};
    Match m(rules, 3, areas);
    m.addParticipant("a1", 0);
    m.update(0, MatchWorld());
    WeaponState* w = m.respawn().weapon("a1", "rifle_iv7");
    check(w != nullptr && w->enabled(), "zbran po spawnu");
    if (w != nullptr) {
      w->update(100000, true);
      w->update(1, false);
      m.kill("a1");
      for (DisableReason r : {DisableReason::Sprint, DisableReason::Switch, DisableReason::Menu, DisableReason::Results,
                              DisableReason::Other}) {
        w->enable(r);
      }
      check(w->lifeLocked() && !w->enabled() && w->update(500000, true) == 0 && w->reload() == ReloadResult::RejectedDisabled,
            "mrtvy: enable() zadneho duvodu neodemkne zamek zivota");
      m.disableInput("a1", DisableReason::Menu);
      m.update(5000000, MatchWorld());
      check(m.respawn().participant("a1")->state == LifeState::Alive && !w->lifeLocked() && w->disabledBy(DisableReason::Menu) &&
              !w->enabled(),
            "respawn s otevrenym menu: zamek menu trva");
      w->update(1, false);
      check(w->update(100000, true) == 0, "zbran se zamkem menu nestrili");
      m.enableInput("a1", DisableReason::Menu);
      w->update(1, false);
      check(w->enabled() && w->update(16667, true) == 1, "po zavreni menu strili novy stisk");
      check(m.enableInput("zz", DisableReason::Menu) == InputLockResult::UnknownId, "enableInput neznameho id");
    }
  }

  std::cout << "unit: " << g_checks << " kontrol, " << g_failures << " selhani\n";
  return g_failures == 0 ? 0 : 1;
}
