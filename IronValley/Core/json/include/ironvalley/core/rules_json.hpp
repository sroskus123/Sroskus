// Nacteni Shared/config/rules.json pres nlohmann::json (testy a nastroje; UE pouzije vlastni JSON a validateRules()).
// Kontroly jsou 1:1 shodne s Web/src/core/rules.js (typy, rozsahy pred prevodem, prevod na mikrosekundy).
#pragma once

#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "ironvalley/core/rules.hpp"

namespace iv::core {

/// Zkompiluje pravidla. Vraci true pri uspechu; jinak vyplni errors (a out je nedefinovany).
bool rulesFromJson(const nlohmann::json& raw, Rules& out, std::vector<std::string>& errors);

/// Kanonicka JSON podoba zkompilovanych pravidel (stejna jako rulesSnapshot() v JS).
nlohmann::json rulesToJson(const Rules& rules);

/// JSON Merge Patch (RFC 7386): objekty se slucuji, null klic odstrani, ostatni nahradi.
nlohmann::json mergePatch(const nlohmann::json& target, const nlohmann::json& patch);

}  // namespace iv::core
