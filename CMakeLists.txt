cmake_minimum_required(VERSION 3.20)

if (APPLE)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "Minimum OS X deployment version")
endif()

project(SnowboardKids2Recompiled LANGUAGES C CXX)
set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(SK2_GAME_VERSION "$ENV{GAME_VERSION}")
string(STRIP "${SK2_GAME_VERSION}" SK2_GAME_VERSION)

if(SK2_GAME_VERSION MATCHES "^v[0-9]")
    string(SUBSTRING "${SK2_GAME_VERSION}" 1 -1 SK2_GAME_VERSION)
endif()

if(SK2_GAME_VERSION STREQUAL "")
    find_package(Git QUIET)
    if(NOT Git_FOUND)
        message(FATAL_ERROR "GAME_VERSION is unset and Git was not found. Set GAME_VERSION to a semantic version.")
    endif()

    execute_process(
        COMMAND "${GIT_EXECUTABLE}" rev-parse HEAD
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        RESULT_VARIABLE SK2_GIT_HASH_RESULT
        OUTPUT_VARIABLE SK2_GIT_HASH
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" tag --merged HEAD --sort=-version:refname
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        RESULT_VARIABLE SK2_GIT_TAGS_RESULT
        OUTPUT_VARIABLE SK2_GIT_TAGS
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )

    string(LENGTH "${SK2_GIT_HASH}" SK2_GIT_HASH_LENGTH)
    if(NOT SK2_GIT_HASH_RESULT EQUAL 0 OR SK2_GIT_HASH_LENGTH LESS 4 OR NOT SK2_GIT_HASH MATCHES "^[0-9a-fA-F]+$")
        message(FATAL_ERROR "GAME_VERSION is unset and the current Git commit could not be read.")
    endif()
    if(NOT SK2_GIT_TAGS_RESULT EQUAL 0)
        message(FATAL_ERROR "GAME_VERSION is unset and the repository's Git tags could not be read.")
    endif()

    string(REPLACE "\r" "" SK2_GIT_TAGS "${SK2_GIT_TAGS}")
    string(REPLACE "\n" ";" SK2_GIT_TAG_LIST "${SK2_GIT_TAGS}")
    foreach(SK2_GIT_TAG IN LISTS SK2_GIT_TAG_LIST)
        if(SK2_GIT_TAG MATCHES "^v[0-9]+\\.[0-9]+\\.[0-9]+$")
            string(SUBSTRING "${SK2_GIT_TAG}" 1 -1 SK2_RELEASE_VERSION)
            break()
        endif()
    endforeach()

    if(NOT DEFINED SK2_RELEASE_VERSION)
        message(FATAL_ERROR
            "GAME_VERSION is unset and no reachable vX.Y.Z release tag was found. "
            "Fetch tags or set GAME_VERSION explicitly."
        )
    endif()

    math(EXPR SK2_GIT_HASH_SUFFIX_OFFSET "${SK2_GIT_HASH_LENGTH} - 4")
    string(SUBSTRING "${SK2_GIT_HASH}" "${SK2_GIT_HASH_SUFFIX_OFFSET}" 4 SK2_GIT_HASH_SUFFIX)
    set(SK2_GAME_VERSION "${SK2_RELEASE_VERSION}+${SK2_GIT_HASH_SUFFIX}")
endif()

if(NOT SK2_GAME_VERSION MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+([+-][0-9A-Za-z.-]+)?$")
    message(FATAL_ERROR
        "Invalid GAME_VERSION '${SK2_GAME_VERSION}'. "
        "Expected X.Y.Z with an optional -suffix or +suffix."
    )
endif()

message(STATUS "Snowboard Kids 2 game version: ${SK2_GAME_VERSION}")
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated")
configure_file(
    "${CMAKE_SOURCE_DIR}/cmake/sk2_game_version.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/sk2_game_version.h"
    @ONLY
)

set(SK2_N64MODERNRUNTIME_SOURCE_DIR "${CMAKE_SOURCE_DIR}/lib/N64ModernRuntime")
set(SK2_RECOMP_FRONTEND_SOURCE_DIR "${CMAKE_SOURCE_DIR}/lib/RecompFrontend")
set(SK2_RT64_SOURCE_DIR "${CMAKE_SOURCE_DIR}/lib/rt64")
set(SK2_N64MODERNRUNTIME_BINARY_DIR "${CMAKE_BINARY_DIR}/lib/N64ModernRuntime")
set(SK2_RECOMP_FRONTEND_BINARY_DIR "${CMAKE_BINARY_DIR}/lib/RecompFrontend")
set(SK2_RT64_BINARY_DIR "${CMAKE_BINARY_DIR}/rt64")

if(CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch")
    set(SK2_SWITCH_DEPS_ROOT "" CACHE PATH
        "Disposable patched dependency tree prepared by switch-build.sh"
    )
    if(NOT SK2_SWITCH_DEPS_ROOT STREQUAL "")
        set(SK2_N64MODERNRUNTIME_SOURCE_DIR "${SK2_SWITCH_DEPS_ROOT}/N64ModernRuntime")
        set(SK2_RECOMP_FRONTEND_SOURCE_DIR "${SK2_SWITCH_DEPS_ROOT}/RecompFrontend")
        set(SK2_RT64_SOURCE_DIR "${SK2_SWITCH_DEPS_ROOT}/rt64")
        set(SK2_N64MODERNRUNTIME_BINARY_DIR "${CMAKE_BINARY_DIR}/switch-deps/N64ModernRuntime")
        set(SK2_RECOMP_FRONTEND_BINARY_DIR "${CMAKE_BINARY_DIR}/switch-deps/RecompFrontend")
        set(SK2_RT64_BINARY_DIR "${CMAKE_BINARY_DIR}/switch-deps/rt64")
    endif()
endif()

# The Horizon OS port is being brought up in layers. The bootstrap target is a
# small, hardware-runnable NRO that validates the devkitA64, libnx, SDL2, audio,
# controller, and SD-card path before the much larger RT64 Vulkan integration is
# enabled. Keeping it as an early return also avoids perturbing desktop builds.
if(CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch")
    option(
        SK2_SWITCH_BOOTSTRAP_ONLY
        "Build the Switch platform bootstrap NRO instead of the game runtime"
        ON
    )
    option(
        SK2_SWITCH_CORE_PROBE_ONLY
        "Cross-build the complete runtime/frontend/RT64 stack without generated game code"
        ON
    )

    if(SK2_SWITCH_BOOTSTRAP_ONLY)
        add_subdirectory(switch)
        return()
    endif()

    if(SK2_SWITCH_DEPS_ROOT STREQUAL "")
        message(FATAL_ERROR
            "Full Switch builds require disposable patched dependencies. "
            "Run scripts/switch-build.sh core or scripts/switch-build.sh full."
        )
    endif()
    foreach(SK2_SWITCH_DEPENDENCY_DIR IN ITEMS
        "${SK2_N64MODERNRUNTIME_SOURCE_DIR}"
        "${SK2_RECOMP_FRONTEND_SOURCE_DIR}"
        "${SK2_RT64_SOURCE_DIR}"
    )
        if(NOT IS_DIRECTORY "${SK2_SWITCH_DEPENDENCY_DIR}")
            message(FATAL_ERROR
                "Switch dependency source is missing: ${SK2_SWITCH_DEPENDENCY_DIR}. "
                "Run scripts/prepare-switch-dependencies.sh."
            )
        endif()
    endforeach()

    find_package(PkgConfig REQUIRED)
    pkg_check_modules(SDL2 REQUIRED IMPORTED_TARGET sdl2)
    pkg_check_modules(FREETYPE REQUIRED IMPORTED_TARGET freetype2)

    if(NOT TARGET SDL2::SDL2)
        add_library(SDL2::SDL2 ALIAS PkgConfig::SDL2)
    endif()

    set(SDL2_FOUND TRUE)
    set(SDL2_LIBRARIES SDL2::SDL2)

    # RecompFrontend reuses RT64's shader helper functions from the parent
    # scope, so provide runnable host DXC settings before adding either tree.
    set(DXC_SPV_OPTS "-spirv" "-fspv-target-env=vulkan1.0" "-fvk-use-dx-layout")
    set(DXC_PS_OPTS "-I${CMAKE_SOURCE_DIR}/src" "-E" "PSMain" "-T" "ps_6_0" "-D" "DYNAMIC_RENDER_PARAMS")
    set(DXC_VS_OPTS "-I${CMAKE_SOURCE_DIR}/src" "-E" "VSMain" "-T" "vs_6_0" "-D" "DYNAMIC_RENDER_PARAMS" "-fvk-invert-y")
    if(CMAKE_HOST_APPLE)
        if(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
            set(DXC
                "DYLD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/lib/x64"
                "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/x64/dxc-macos"
            )
        else()
            set(DXC
                "DYLD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/lib/arm64"
                "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/arm64/dxc-macos"
            )
        endif()
    endif()

    set(SK2_HOST_FILE_TO_C
        "${CMAKE_SOURCE_DIR}/build-tools/file-to-c-host/file_to_c"
        CACHE FILEPATH "Runnable host file_to_c executable"
    )
    if(NOT EXISTS "${SK2_HOST_FILE_TO_C}")
        message(FATAL_ERROR
            "The host file_to_c tool is missing. Run "
            "scripts/generate-recompiled-code.sh after placing snowboardkids2.z64 "
            "in the repository root."
        )
    endif()

    set(SK2_HOST_N64RECOMP
        "${CMAKE_SOURCE_DIR}/build-tools/n64recomp-host/N64Recomp"
        CACHE FILEPATH "Runnable host N64Recomp executable"
    )
    if(NOT EXISTS "${SK2_HOST_N64RECOMP}")
        message(FATAL_ERROR
            "The host N64Recomp tool is missing. Run scripts/generate-recompiled-code.sh."
        )
    endif()

    set(SK2_SWITCH_NVK_ROOT "" CACHE PATH
        "Path to the packaged switch-nvk tree (include/ and lib/libvulkan.a)"
    )
    if(SK2_SWITCH_NVK_ROOT STREQUAL "" AND DEFINED ENV{SK2_SWITCH_NVK_ROOT})
        set(SK2_SWITCH_NVK_ROOT "$ENV{SK2_SWITCH_NVK_ROOT}")
    endif()

    # These searches are constrained to SK2_SWITCH_NVK_ROOT. Clear results
    # from an older package location before resolving the current root.
    unset(SK2_SWITCH_NVK_INCLUDE_DIR CACHE)
    unset(SK2_SWITCH_NVK_LIBRARY CACHE)
    unset(SK2_SWITCH_NVK_EXPAT_LIBRARY CACHE)
    find_path(SK2_SWITCH_NVK_INCLUDE_DIR
        NAMES vulkan/vulkan.h
        PATHS "${SK2_SWITCH_NVK_ROOT}/include"
        NO_DEFAULT_PATH
    )
    find_library(SK2_SWITCH_NVK_LIBRARY
        NAMES vulkan libvulkan.a
        PATHS "${SK2_SWITCH_NVK_ROOT}/lib"
        NO_DEFAULT_PATH
    )
    find_library(SK2_SWITCH_NVK_EXPAT_LIBRARY
        NAMES expat libexpat.a
        PATHS "${SK2_SWITCH_NVK_ROOT}/lib"
        NO_DEFAULT_PATH
    )
    if(NOT SK2_SWITCH_NVK_INCLUDE_DIR OR
       NOT SK2_SWITCH_NVK_LIBRARY OR
       NOT SK2_SWITCH_NVK_EXPAT_LIBRARY)
        message(FATAL_ERROR
            "A packaged switch-nvk build is required for the full game. Set "
            "SK2_SWITCH_NVK_ROOT to an nvk-switch directory containing "
            "include/, lib/libvulkan.a, and lib/libexpat.a."
        )
    endif()

    add_library(SwitchNVK STATIC IMPORTED GLOBAL)
    set_target_properties(SwitchNVK PROPERTIES
        IMPORTED_LOCATION "${SK2_SWITCH_NVK_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${SK2_SWITCH_NVK_INCLUDE_DIR}"
    )

    add_compile_definitions(
        SK2_SWITCH=1
        _GNU_SOURCE
        RECOMP_SWITCH_APP_FOLDER="sdmc:/switch/snowboardkids2-recompiled"
        PLUME_SDL_VULKAN_ENABLED
        RT64_SDL_WINDOW_VULKAN
        VK_USE_PLATFORM_VI_NN
    )
    include_directories(BEFORE "${CMAKE_SOURCE_DIR}/switch/compat")
endif()

if (CMAKE_CXX_COMPILER_ID STREQUAL "Clang" AND CMAKE_CXX_SIMULATE_ID STREQUAL "MSVC")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-everything /W4")
endif()

# Opt out of constexpr mutex constructor on windows to prevent vcredist issues
if (WIN32)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -D_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR")
    add_compile_definitions(__PRFCHWINTRIN_H)
endif()

if (APPLE)
    enable_language(OBJC OBJCXX)
endif()

if (CMAKE_SYSTEM_NAME MATCHES "Linux")
    option(RECOMP_FLATPAK "Configure the build for Flatpak compatibility." OFF)
endif()

# Avoid warning about DOWNLOAD_EXTRACT_TIMESTAMP in CMake 3.24:
if (CMAKE_VERSION VERSION_GREATER_EQUAL "3.24.0")
    cmake_policy(SET CMP0135 NEW)
endif()

set (CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set (CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

if (WIN32)
    set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/lib/")
endif()

set(RT64_STATIC TRUE)
set(RT64_SDL_WINDOW_VULKAN TRUE)
add_compile_definitions(HLSL_CPU)

if (RECOMP_FLATPAK)
    add_compile_definitions(RECOMP_FLATPAK)
endif()

add_subdirectory(${SK2_RT64_SOURCE_DIR} ${SK2_RT64_BINARY_DIR})

set(BUILD_SHARED_LIBS OFF)

add_subdirectory(${SK2_N64MODERNRUNTIME_SOURCE_DIR} ${SK2_N64MODERNRUNTIME_BINARY_DIR})

target_include_directories(rt64 PRIVATE ${SK2_RT64_BINARY_DIR}/src)

if (CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch" AND SK2_SWITCH_CORE_PROBE_ONLY)
    set(RECOMP_FRONTEND_N64MODERNRUNTIME_PATH ${SK2_N64MODERNRUNTIME_SOURCE_DIR})
    set(RECOMP_FRONTEND_RT64_PATH ${SK2_RT64_SOURCE_DIR})
    add_subdirectory(${SK2_RECOMP_FRONTEND_SOURCE_DIR} ${SK2_RECOMP_FRONTEND_BINARY_DIR})

    add_executable(SnowboardKids2SwitchCoreProbe switch/core_probe.cpp switch/texture_probe.cpp switch/full_main.cpp)
    target_include_directories(SnowboardKids2SwitchCoreProbe PRIVATE
        ${SK2_RECOMP_FRONTEND_SOURCE_DIR}/recompui/src
        ${SK2_RECOMP_FRONTEND_SOURCE_DIR}/recompui/include
        ${SK2_RT64_SOURCE_DIR}/src/contrib/plume
        ${CMAKE_CURRENT_BINARY_DIR}/src
        ${SDL2_INCLUDE_DIRS}
    )
    target_link_options(SnowboardKids2SwitchCoreProbe PRIVATE
        "-Wl,--wrap=open"
        "-Wl,--wrap=close"
        "-Wl,--wrap=stat"
        "-Wl,--wrap=lstat"
        "-Wl,--allow-multiple-definition"
        # Plume's static archive retains this SDL helper even though the
        # headless probe never creates a window. Force it into SDL's archive
        # before Plume appears later in the transitive static-link order.
        "-Wl,--undefined=SDL_GetWindowSizeInPixels"
    )
    target_link_libraries(SnowboardKids2SwitchCoreProbe PRIVATE
        recompui
        recompinput
        librecomp
        ultramodern
        rt64
        PkgConfig::SDL2
        PkgConfig::FREETYPE
        "-Wl,--whole-archive"
        SwitchNVK
        "-Wl,--no-whole-archive"
        "${SK2_SWITCH_NVK_EXPAT_LIBRARY}"
    )

    set(SK2_SWITCH_CORE_NACP "${CMAKE_CURRENT_BINARY_DIR}/snowboardkids2-core-probe.nacp")
    nx_generate_nacp(
        OUTPUT "${SK2_SWITCH_CORE_NACP}"
        NAME "SK2 Runtime + NVK Probe"
        AUTHOR "Snowboard Kids 2 Recompiled"
        VERSION "${SK2_GAME_VERSION}"
    )
    nx_create_nro(
        SnowboardKids2SwitchCoreProbe
        OUTPUT "${CMAKE_BINARY_DIR}/snowboardkids2-core-probe.nro"
        NACP "${SK2_SWITCH_CORE_NACP}"
    )
    return()
endif()

# RecompiledFuncs - Library containing the primary recompiler output
add_library(RecompiledFuncs STATIC)

target_compile_options(RecompiledFuncs PRIVATE
    # -Wno-unused-but-set-variable
    -fno-strict-aliasing
    -Wno-unused-variable
    -Wno-implicit-function-declaration
)

target_include_directories(RecompiledFuncs PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/ultramodern/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/librecomp/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/N64Recomp/include
)

file(GLOB FUNC_C_SOURCES ${CMAKE_SOURCE_DIR}/RecompiledFuncs/*.c)
file(GLOB FUNC_CXX_SOURCES ${CMAKE_SOURCE_DIR}/RecompiledFuncs/*.cpp)

target_sources(RecompiledFuncs PRIVATE ${FUNC_C_SOURCES} ${FUNC_CXX_SOURCES})

# PatchesLib - Library containing the recompiled output for any custom function patches
add_library(PatchesLib STATIC)

target_compile_options(PatchesLib PRIVATE
    # -Wno-unused-but-set-variable
    -fno-strict-aliasing
    -Wno-unused-variable
    -Wno-implicit-function-declaration
)

target_include_directories(PatchesLib PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/ultramodern/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/librecomp/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/N64Recomp/include
)

target_sources(PatchesLib PRIVATE
    ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches.c
    ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches_bin.c
)

set_source_files_properties(${CMAKE_SOURCE_DIR}/RecompiledPatches/patches.c PROPERTIES COMPILE_FLAGS -fno-strict-aliasing)

# Build patches elf
if(NOT DEFINED PATCHES_C_COMPILER)
    if(APPLE AND EXISTS "/opt/homebrew/opt/llvm/bin/clang")
        set(PATCHES_C_COMPILER "/opt/homebrew/opt/llvm/bin/clang")
    elseif(APPLE AND EXISTS "/usr/local/opt/llvm/bin/clang")
        set(PATCHES_C_COMPILER "/usr/local/opt/llvm/bin/clang")
    else()
        set(PATCHES_C_COMPILER clang)
    endif()
endif()

if(NOT DEFINED PATCHES_LD)
    if(APPLE AND EXISTS "/opt/homebrew/bin/ld.lld")
        set(PATCHES_LD "/opt/homebrew/bin/ld.lld")
    elseif(APPLE AND EXISTS "/usr/local/bin/ld.lld")
        set(PATCHES_LD "/usr/local/bin/ld.lld")
    else()
        set(PATCHES_LD ld.lld)
    endif()
endif()

if(WIN32)
    set(PATCH_RECOMP_ATTEMPTS 3)
else()
    set(PATCH_RECOMP_ATTEMPTS 1)
endif()

add_custom_target(PatchesBin
    COMMAND ${CMAKE_COMMAND} -E env CC=${PATCHES_C_COMPILER} LD=${PATCHES_LD} make
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}/patches
    BYPRODUCTS ${CMAKE_SOURCE_DIR}/patches/patches.elf
)

# Generate patches_bin.c from patches.bin
add_custom_command(OUTPUT ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches_bin.c
    COMMAND file_to_c ${CMAKE_SOURCE_DIR}/patches/patches.bin mm_patches_bin ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches_bin.c ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches_bin.h
    DEPENDS ${CMAKE_SOURCE_DIR}/patches/patches.bin
)

# Recompile patches elf into patches.c and patches.bin
add_custom_command(OUTPUT
                       ${CMAKE_SOURCE_DIR}/patches/patches.bin
                       ${CMAKE_SOURCE_DIR}/RecompiledPatches/patches.c
                       ${CMAKE_SOURCE_DIR}/RecompiledPatches/recomp_overlays.inl
                       ${CMAKE_SOURCE_DIR}/RecompiledPatches/funcs.h
                   # TODO: Look into why modifying patches requires two builds to take
                   COMMAND ${CMAKE_COMMAND}
                           -DRUN_EXECUTABLE=${SK2_HOST_N64RECOMP}
                           -DRUN_ARGUMENTS=patches.toml
                           -DRUN_ATTEMPTS=${PATCH_RECOMP_ATTEMPTS}
                           -DRUN_DELAY_SECONDS=2
                           -DRUN_WORKING_DIRECTORY=${CMAKE_SOURCE_DIR}
                           -P ${CMAKE_SOURCE_DIR}/cmake/RunWithRetries.cmake
                   WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
                   DEPENDS ${CMAKE_SOURCE_DIR}/patches/patches.elf
)

# Main executable
add_executable(SnowboardKids2Recompiled)

set (SOURCES
    ${CMAKE_SOURCE_DIR}/src/main/main.cpp
    ${CMAKE_SOURCE_DIR}/src/main/sk2_launcher.cpp
    ${CMAKE_SOURCE_DIR}/src/main/sk2_theme.cpp
    ${CMAKE_SOURCE_DIR}/src/main/support.cpp
    ${CMAKE_SOURCE_DIR}/src/main/register_overlays.cpp
    ${CMAKE_SOURCE_DIR}/src/main/register_patches.cpp

    ${CMAKE_SOURCE_DIR}/src/game/config.cpp
    ${CMAKE_SOURCE_DIR}/src/game/quicksaving.cpp
    ${CMAKE_SOURCE_DIR}/src/game/recomp_api.cpp
    ${CMAKE_SOURCE_DIR}/src/game/recomp_actor_api.cpp
    ${CMAKE_SOURCE_DIR}/src/game/recomp_data_api.cpp

    ${CMAKE_SOURCE_DIR}/rsp/aspMain.cpp
    # ${CMAKE_SOURCE_DIR}/rsp/njpgdspMain.cpp
)

if (APPLE)
    list(APPEND SOURCES ${CMAKE_SOURCE_DIR}/src/main/support_apple.mm)
endif()

if (CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch")
    list(APPEND SOURCES ${CMAKE_SOURCE_DIR}/switch/full_main.cpp)
endif()

target_include_directories(SnowboardKids2Recompiled PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/N64Recomp/include
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/thirdparty
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/thirdparty/concurrentqueue
    ${SK2_RECOMP_FRONTEND_SOURCE_DIR}/recompinput/include
    ${SK2_RECOMP_FRONTEND_SOURCE_DIR}/recompui/include
    ${SK2_RECOMP_FRONTEND_SOURCE_DIR}/recompui/src
    ${SK2_RT64_SOURCE_DIR}/src/contrib
    ${SK2_RT64_SOURCE_DIR}/src/contrib/hlslpp/include
    ${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/inc
    ${SK2_RT64_SOURCE_DIR}/src
    ${SK2_RT64_SOURCE_DIR}/src/rhi
    ${SK2_RT64_SOURCE_DIR}/src/render
    ${CMAKE_SOURCE_DIR}/lib/freetype-windows-binaries/include
    ${SK2_RT64_SOURCE_DIR}/src/contrib/nativefiledialog-extended/src/include
    ${CMAKE_BINARY_DIR}/shaders
    ${CMAKE_CURRENT_BINARY_DIR}/generated
    ${CMAKE_CURRENT_BINARY_DIR}
)

if (CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch")
    target_include_directories(SnowboardKids2Recompiled PRIVATE
        ${SDL2_INCLUDE_DIRS}
        ${FREETYPE_INCLUDE_DIRS}
        ${SK2_SWITCH_NVK_INCLUDE_DIR}
    )
    target_link_libraries(SnowboardKids2Recompiled PRIVATE
        PkgConfig::SDL2
        PkgConfig::FREETYPE
    )
    target_link_options(SnowboardKids2Recompiled PRIVATE
        "-Wl,--wrap=open"
        "-Wl,--wrap=close"
        "-Wl,--wrap=stat"
        "-Wl,--wrap=lstat"
        "-Wl,--allow-multiple-definition"
    )
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8 AND CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
    target_compile_options(SnowboardKids2Recompiled PRIVATE
        -march=nehalem
        # -march=core2
        # -msse4.1 # added for core2
        -fno-strict-aliasing
        -fms-extensions
    )
else()
    target_compile_options(SnowboardKids2Recompiled PRIVATE
        -fno-strict-aliasing
        -fms-extensions
    )
endif()

if (MSVC)
    # Disable identical code folding, since this breaks mod function patching as multiple functions can get merged into one.
    target_link_options(SnowboardKids2Recompiled PRIVATE /OPT:NOICF)
elseif (APPLE)
    # Use a wrapper around ld64 that respects segprot's `max_prot` value in order
    # to make our executable memory writable (required for mod function patching)
    target_link_options(SnowboardKids2Recompiled PRIVATE
        "-fuse-ld=${CMAKE_SOURCE_DIR}/.github/macos/ld64"
    )
endif()

if (WIN32)
    include(FetchContent)

    if (DEFINED ENV{SDL2_VERSION})
        set(SDL2_VERSION $ENV{SDL2_VERSION})
    else()
        set(SDL2_VERSION "2.30.3")
    endif()

    # Fetch SDL2 on windows
    FetchContent_Declare(
        sdl2
        URL https://github.com/libsdl-org/SDL/releases/download/release-${SDL2_VERSION}/SDL2-devel-${SDL2_VERSION}-VC.zip
    )
    FetchContent_MakeAvailable(sdl2)
    target_include_directories(SnowboardKids2Recompiled PRIVATE
        ${sdl2_SOURCE_DIR}/include
    )
    target_link_directories(SnowboardKids2Recompiled PRIVATE
        ${sdl2_SOURCE_DIR}/lib/x64
    )

    # Copy SDL2 and dxc DLLs to output folder as post build step
    add_custom_command(TARGET SnowboardKids2Recompiled POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${sdl2_SOURCE_DIR}/lib/x64/SDL2.dll"
            "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/x64/dxil.dll"
            "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/x64/dxcompiler.dll"
            $<TARGET_FILE_DIR:SnowboardKids2Recompiled>)

    set_target_properties(
        SnowboardKids2Recompiled
        PROPERTIES
            LINK_FLAGS_DEBUG "/SUBSYSTEM:CONSOLE"
            LINK_FLAGS_RELEASE "/SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup"
            LINK_FLAGS_RELWITHDEBINFO "/SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup"
            LINK_FLAGS_MINSIZEREL "/SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup"
    )

    target_sources(SnowboardKids2Recompiled PRIVATE ${CMAKE_SOURCE_DIR}/icons/app.rc)
    target_link_libraries(SnowboardKids2Recompiled PRIVATE SDL2 Winmm.lib)
endif()

if (APPLE)
    find_package(SDL2 REQUIRED)
    target_include_directories(SnowboardKids2Recompiled PRIVATE ${SDL2_INCLUDE_DIRS})

    set(CMAKE_THREAD_PREFER_PTHREAD TRUE)
    set(THREADS_PREFER_PTHREAD_FLAG TRUE)
    find_package(Threads REQUIRED)

    target_link_libraries(SnowboardKids2Recompiled PRIVATE ${CMAKE_DL_LIBS} Threads::Threads SDL2::SDL2)

    include(${CMAKE_SOURCE_DIR}/.github/macos/apple_bundle.cmake)
endif()

if (CMAKE_SYSTEM_NAME MATCHES "Linux")
    find_package(SDL2 REQUIRED)
    find_package(X11 REQUIRED)

    add_compile_definitions(
        "PLUME_SDL_VULKAN_ENABLED"
        "RT64_SDL_WINDOW_VULKAN"
    )

    # Generate icon_bytes.c from the app icon PNG.
    add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/icon_bytes.c ${CMAKE_CURRENT_BINARY_DIR}/icon_bytes.h
        COMMAND file_to_c ${CMAKE_SOURCE_DIR}/icons/512.png icon_bytes ${CMAKE_CURRENT_BINARY_DIR}/icon_bytes.c ${CMAKE_CURRENT_BINARY_DIR}/icon_bytes.h
        DEPENDS ${CMAKE_SOURCE_DIR}/icons/512.png
    )
    target_sources(SnowboardKids2Recompiled PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/icon_bytes.c)

    message(STATUS "SDL2_FOUND = ${SDL2_FOUND}")
    message(STATUS "SDL2_INCLUDE_DIRS = ${SDL2_INCLUDE_DIRS}")

    target_include_directories(SnowboardKids2Recompiled PRIVATE ${SDL2_INCLUDE_DIRS})

    message(STATUS "X11_FOUND = ${X11_FOUND}")
    message(STATUS "X11_Xrandr_FOUND = ${X11_Xrandr_FOUND}")
    message(STATUS "X11_INCLUDE_DIR = ${X11_INCLUDE_DIR}")
    message(STATUS "X11_LIBRARIES = ${X11_LIBRARIES}")

    target_include_directories(SnowboardKids2Recompiled PRIVATE ${X11_INCLUDE_DIR} ${X11_Xrandr_INCLUDE_PATH})
    target_link_libraries(SnowboardKids2Recompiled PRIVATE ${X11_LIBRARIES} ${X11_Xrandr_LIB})

    find_package(Freetype REQUIRED)

    message(STATUS "FREETYPE_FOUND = ${FREETYPE_FOUND}")
    message(STATUS "FREETYPE_INCLUDE_DIRS = ${FREETYPE_INCLUDE_DIRS}")
    message(STATUS "FREETYPE_LIBRARIES = ${FREETYPE_LIBRARIES}")

    include_directories(${FREETYPE_LIBRARIES})
    target_link_libraries(SnowboardKids2Recompiled PRIVATE ${FREETYPE_LIBRARIES} SDL2::SDL2)

    set(CMAKE_THREAD_PREFER_PTHREAD TRUE)
    set(THREADS_PREFER_PTHREAD_FLAG TRUE)
    find_package(Threads REQUIRED)

    target_link_libraries(SnowboardKids2Recompiled PRIVATE "-latomic -static-libstdc++" ${CMAKE_DL_LIBS} Threads::Threads)
endif()

# TODO fix the rt64 CMake script so that this doesn't need to be duplicated here
# For DXC
set (DXC_COMMON_OPTS "-I${PROJECT_SOURCE_DIR}/src")
set (DXC_DXIL_OPTS "-Wno-ignored-attributes")
set (DXC_SPV_OPTS "-spirv" "-fspv-target-env=vulkan1.0" "-fvk-use-dx-layout")
set (DXC_PS_OPTS "${DXC_COMMON_OPTS}" "-E" "PSMain" "-T ps_6_0" "-D DYNAMIC_RENDER_PARAMS")
set (DXC_VS_OPTS "${DXC_COMMON_OPTS}" "-E" "VSMain" "-T vs_6_0" "-D DYNAMIC_RENDER_PARAMS" "-fvk-invert-y")
set (DXC_CS_OPTS "${DXC_COMMON_OPTS}" "-E" "CSMain" "-T cs_6_0")
set (DXC_GS_OPTS "${DXC_COMMON_OPTS}" "-E" "GSMain" "-T gs_6_0")
set (DXC_RT_OPTS "${DXC_COMMON_OPTS}" "-D" "RT_SHADER" "-T" "lib_6_3" "-fspv-target-env=vulkan1.1spirv1.4" "-fspv-extension=SPV_KHR_ray_tracing" "-fspv-extension=SPV_EXT_descriptor_indexing")

if (${WIN32})
    set (DXC "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/x64/dxc.exe")
    add_compile_definitions(NOMINMAX)
else()
    if (CMAKE_HOST_APPLE)
        # Apple's binary is universal, so it'll work on both x86_64 and arm64
        set (DXC "DYLD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/lib/arm64" "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/arm64/dxc-macos")
        if(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
            set(SPIRVCROSS "DYLD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/spirv-cross/lib/x64" "${SK2_RT64_SOURCE_DIR}/src/contrib/spirv-cross/bin/x64/spirv-cross")
        else()
            set(SPIRVCROSS "DYLD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/spirv-cross/lib/arm64" "${SK2_RT64_SOURCE_DIR}/src/contrib/spirv-cross/bin/x64/spirv-cross")
        endif()
    else()
        if(CMAKE_SIZEOF_VOID_P EQUAL 8 AND CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
            set (DXC "LD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/lib/x64" "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/x64/dxc-linux")
        else()
            set (DXC "LD_LIBRARY_PATH=${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/lib/arm64" "${SK2_RT64_SOURCE_DIR}/src/contrib/dxc/bin/arm64/dxc-linux")
        endif()
    endif()
endif()

set(RECOMP_FRONTEND_N64MODERNRUNTIME_PATH ${SK2_N64MODERNRUNTIME_SOURCE_DIR})
set(RECOMP_FRONTEND_RT64_PATH ${SK2_RT64_SOURCE_DIR})

add_subdirectory(${SK2_RECOMP_FRONTEND_SOURCE_DIR} ${SK2_RECOMP_FRONTEND_BINARY_DIR})

target_include_directories(recompui BEFORE PRIVATE
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/thirdparty
)
target_include_directories(recompinput BEFORE PRIVATE
    ${SK2_N64MODERNRUNTIME_SOURCE_DIR}/thirdparty
)

target_link_libraries(SnowboardKids2Recompiled PRIVATE
    PatchesLib
    RecompiledFuncs
    recompui
    recompinput
    librecomp
    ultramodern
    rt64
    nfd
)

if (CMAKE_SYSTEM_NAME STREQUAL "NintendoSwitch")
    target_link_libraries(SnowboardKids2Recompiled PRIVATE
        "-Wl,--whole-archive"
        SwitchNVK
        "-Wl,--no-whole-archive"
        "${SK2_SWITCH_NVK_EXPAT_LIBRARY}"
    )

    set(SK2_SWITCH_NACP "${CMAKE_CURRENT_BINARY_DIR}/snowboardkids2-recompiled.nacp")
    nx_generate_nacp(
        OUTPUT "${SK2_SWITCH_NACP}"
        NAME "Snowboard Kids 2: Recompiled"
        AUTHOR "Snowboard Kids 2 Recompiled"
        VERSION "${SK2_GAME_VERSION}"
    )
    nx_create_nro(
        SnowboardKids2Recompiled
        OUTPUT "${CMAKE_BINARY_DIR}/snowboardkids2-recompiled.nro"
        NACP "${SK2_SWITCH_NACP}"
    )
endif()

# Embed all .nrm files in the "mods" directory
file(GLOB NRM_FILES "${CMAKE_SOURCE_DIR}/mods/*.nrm")

set(GENERATED_NRM_SOURCES "")
set(GENERATED_NRM_HEADERS "")

foreach(NRM_FILE ${NRM_FILES})
    get_filename_component(NRM_NAME ${NRM_FILE} NAME_WE)
    set(OUT_C "${CMAKE_CURRENT_BINARY_DIR}/mods/${NRM_NAME}.c")
    set(OUT_H "${CMAKE_CURRENT_BINARY_DIR}/mods/${NRM_NAME}.h")

    add_custom_command(
        OUTPUT ${OUT_C} ${OUT_H}
        COMMAND file_to_c ${NRM_FILE} ${NRM_NAME} ${OUT_C} ${OUT_H}
        DEPENDS ${NRM_FILE} file_to_c
    )

    list(APPEND GENERATED_NRM_SOURCES ${OUT_C})
    list(APPEND GENERATED_NRM_HEADERS ${OUT_H})
endforeach()

target_sources(SnowboardKids2Recompiled PRIVATE ${GENERATED_NRM_SOURCES})
if(GENERATED_NRM_HEADERS)
    add_custom_target(EmbeddedMods DEPENDS ${GENERATED_NRM_SOURCES} ${GENERATED_NRM_HEADERS})
    add_dependencies(SnowboardKids2Recompiled EmbeddedMods)
endif()

target_sources(SnowboardKids2Recompiled PRIVATE ${SOURCES})

set_property(TARGET SnowboardKids2Recompiled PROPERTY VS_DEBUGGER_WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
