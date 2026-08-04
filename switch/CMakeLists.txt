find_package(PkgConfig REQUIRED)
pkg_check_modules(SDL2 REQUIRED IMPORTED_TARGET sdl2)

add_executable(SnowboardKids2SwitchBootstrap
    bootstrap_main.cpp
)

target_compile_features(SnowboardKids2SwitchBootstrap PRIVATE cxx_std_20)
target_compile_definitions(SnowboardKids2SwitchBootstrap PRIVATE SK2_SWITCH=1)
target_link_libraries(SnowboardKids2SwitchBootstrap PRIVATE PkgConfig::SDL2)

set(SK2_SWITCH_NACP "${CMAKE_CURRENT_BINARY_DIR}/snowboardkids2-recompiled.nacp")
nx_generate_nacp(
    OUTPUT "${SK2_SWITCH_NACP}"
    NAME "Snowboard Kids 2: Recompiled"
    AUTHOR "Snowboard Kids 2 Recompiled"
    VERSION "${SK2_GAME_VERSION}"
)

nx_create_nro(
    SnowboardKids2SwitchBootstrap
    OUTPUT "${CMAKE_BINARY_DIR}/snowboardkids2-recompiled.nro"
    NACP "${SK2_SWITCH_NACP}"
)
