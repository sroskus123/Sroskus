cmake_minimum_required(VERSION 3.16)
project(IronValleyCore LANGUAGES CXX)

# Ciste C++17 jadro pravidel IRON VALLEY (rozhodnuti D6). Stejne testovaci vektory jako JS jadro (Web/src/core).
#   cmake -S Core -B Core/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build Core/build -j4
#   ctest --test-dir Core/build --output-on-failure

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(IV_SHARED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../Shared" CACHE PATH "Adresar Shared (pravidla a testovaci vektory)")

# Kontrola pameti (use-after-free, preteceni, UB) pro jadro i testy:
#   cmake -S Core -B Core/build-asan -DCMAKE_BUILD_TYPE=Debug -DIV_SANITIZE=ON && cmake --build Core/build-asan -j4
#   ctest --test-dir Core/build-asan --output-on-failure
option(IV_SANITIZE "AddressSanitizer + UndefinedBehaviorSanitizer (GCC/Clang)" OFF)
if(IV_SANITIZE)
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
  else()
    message(FATAL_ERROR "IV_SANITIZE je podporovany jen pro GCC/Clang")
  endif()
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  set(IV_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion)
  # Zadne slucovani nasobeni a scitani (FMA): vzdalenosti ve spawnech musi dat bit po bitu totez co JS.
  set(IV_FP -ffp-contract=off)
elseif(MSVC)
  set(IV_WARNINGS /W4)
  set(IV_FP /fp:precise)
endif()

# --- jadro: bez vyjimek, bez RTTI, bez zavislosti (pouzitelne v UE modulu) ---
add_library(ironvalley_core STATIC
  src/rules.cpp
  src/weapon.cpp
  src/zone.cpp
  src/round.cpp
  src/respawn.cpp
  src/match.cpp)
target_include_directories(ironvalley_core PUBLIC include)
target_compile_options(ironvalley_core PRIVATE ${IV_WARNINGS} ${IV_FP})
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(ironvalley_core PRIVATE -fno-exceptions -fno-rtti)
endif()

# --- nacitani rules.json pres nlohmann/json (testy a nastroje) ---
add_library(ironvalley_core_json STATIC json/src/rules_json.cpp)
target_include_directories(ironvalley_core_json PUBLIC json/include third_party)
target_link_libraries(ironvalley_core_json PUBLIC ironvalley_core)
target_compile_options(ironvalley_core_json PRIVATE ${IV_WARNINGS} ${IV_FP})

# --- testy ---
enable_testing()

add_executable(ivcore_vectors tests/vector_runner.cpp)
target_link_libraries(ivcore_vectors PRIVATE ironvalley_core_json)
target_compile_options(ivcore_vectors PRIVATE ${IV_WARNINGS} ${IV_FP})

add_executable(ivcore_unit tests/unit_tests.cpp)
target_link_libraries(ivcore_unit PRIVATE ironvalley_core_json)
target_compile_options(ivcore_unit PRIVATE ${IV_WARNINGS} ${IV_FP})

set(IV_RULES "${IV_SHARED_DIR}/config/rules.json")
file(GLOB IV_VECTOR_FILES CONFIGURE_DEPENDS "${IV_SHARED_DIR}/testvectors/*.json")
list(SORT IV_VECTOR_FILES)
foreach(vec ${IV_VECTOR_FILES})
  get_filename_component(name "${vec}" NAME_WE)
  add_test(NAME vectors.${name} COMMAND ivcore_vectors --rules "${IV_RULES}" "${vec}")
endforeach()
add_test(NAME unit COMMAND ivcore_unit "${IV_SHARED_DIR}")
# Spoustec nesmi tise ignorovat preklepy a spatne umistene klice ve vektorech (stejny soubor kontroluje JS test).
add_test(NAME runner.malformed
         COMMAND ivcore_vectors --rules "${IV_RULES}" --malformed "${IV_SHARED_DIR}/testvectors/malformed/cases.json")

# Nezavisla referencni kontrola hodnot zavislych na semeni (Python, bez JS/C++ jadra). Spusti se, je-li Python 3 k dispozici.
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
  add_test(NAME seed_reference
           COMMAND ${Python3_EXECUTABLE} "${IV_SHARED_DIR}/testvectors/tools/seed_reference.py" --shared "${IV_SHARED_DIR}")
else()
  message(STATUS "Python 3 nenalezen: test seed_reference se nezaregistruje")
endif()
