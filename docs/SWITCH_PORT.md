# Nintendo Switch port plan

## Goal

Produce a native Horizon OS homebrew build of Snowboard Kids 2: Recompiled with the same broad user experience as Ship of Harkinian on Switch: an NRO launched through Homebrew Menu title takeover, controller-first menus, persistent saves/configuration, user-supplied game data on the SD card, mods, widescreen rendering, and stable audio/video pacing.

The port must not contain or download copyrighted game data. Users will copy their own supported Snowboard Kids 2 ROM to the application directory.

## Architectural finding

Shipwright is a useful product and platform reference, but it is not a drop-in technical base. Shipwright is a decompilation/source port and can use the Switch homebrew OpenGL stack. This project is an N64 static recompilation whose display lists are rendered by RT64. RT64 currently targets Vulkan, D3D12, and Metal; the pinned runtime and renderer have no Horizon OS platform definitions.

That makes this a two-part port:

1. Add the conventional libnx/SDL2/NRO platform layer used by projects such as Shipwright.
2. Bring RT64's Vulkan RHI up on Horizon OS, or implement a new RT64 deko3d RHI.

The first renderer route to evaluate is the open-source `switch-nvk` Mesa/NVK port. It exposes `VK_NN_vi_surface` over libnx `NWindow` and is much closer to RT64's existing Vulkan backend than a new deko3d implementation. It is still young and must be pinned, audited against RT64's required Vulkan features, and tested on real Erista and Mariko hardware. A native deko3d backend remains the fallback if NVK is incomplete or too slow.

## Target SD-card layout

```text
sdmc:/switch/snowboardkids2-recompiled/
├── snowboardkids2-recompiled.nro
├── snowboardkids2.z64
├── recompcontrollerdb.txt
├── assets/
├── mods/
├── config/
└── saves/
```

Like Shipwright, the application should be launched with Homebrew Menu title takeover rather than Album/applet mode. RT64, generated code, UI assets, and mods are unlikely to fit reliably in applet-mode memory.

## Milestones

### M0 — SDK and platform bootstrap (implemented and hardware-validated)

- Cross-configure with devkitPro's `Switch.cmake` and devkitA64.
- Link libnx and the Switch SDL2 port.
- Generate NACP metadata and an NRO.
- Open an accelerated, vsynced SDL window.
- Detect the first SDL game controller and exit with Plus.
- Create and write the persistent application directory on `sdmc:`.
- Visually report storage and title-takeover status on hardware.

The bootstrap is intentionally independent of RT64. It gives renderer work a known-good executable, window, input, storage, and packaging baseline.

Hardware result: the title text rendered and both bootstrap bars were green in
application mode, confirming SDL video/input, SD persistence, and title-takeover
memory on the target console.

### M1 — Core runtime cross-build (implemented)

- Add `NintendoSwitch` platform definitions to N64ModernRuntime, RT64/Plume, and RecompFrontend in maintained dependency forks or upstream patches.
- Add a no-dialog file backend. On Switch, ROMs and mods are discovered from fixed SD-card directories; native desktop file dialogs are not available.
- Route application, config, save, asset, ROM, and mod paths to the layout above.
- Disable desktop-only code: X11, GTK/portal NFD, process spawning, window resizing, mouse/keyboard defaults, and executable preloading.
- Verify pthreads, atomics, C++20 filesystem, EEPROM saves, and the recompiled ARM64 code independently of rendering.
- Decide how runtime mod function patching works under Horizon's executable-memory rules. If W^X transitions are unavailable, start with embedded/data-only mods and gate live code mods with a clear UI capability flag.

The maintained patch sets under `switch/patches/` now cover N64ModernRuntime,
RecompFrontend and its nested SVG library, RT64/ImPlot, and Plume/Volk. Live
code mods are disabled for the first Switch build; embedded and data-only mods
remain available. The complete runtime/frontend/RT64 source stack cross-compiles
for aarch64 and links against the real static NVK package.

Exit gate passed: `SnowboardKids2SwitchCoreProbe.elf` and its NRO link from the
full core stack without generated game code.

### M2 — RT64 Vulkan bring-up (hardware validation in progress)

- Package or document a reproducible, pinned `switch-nvk` build; do not silently depend on a machine-global unversioned driver.
- Teach Plume to create `VkViSurfaceCreateInfoNN` from `nwindowGetDefault()` and request `VK_KHR_surface` plus `VK_NN_vi_surface` directly. Switch SDL2 does not currently provide this Vulkan surface path.
- Load the NVK Vulkan entry points without desktop `dlopen` assumptions.
- Audit RT64's required formats, descriptor limits, synchronization, compute shaders, specialization constants, and memory budget against NVK on Tegra X1.
- Precompile HLSL to SPIR-V on the host and embed the results. Target-side shader compilation is not part of the NRO build.
- Start at 1280x720, FIFO presentation, one frame in flight, no MSAA, no ray tracing, and conservative texture cache sizes.

Exit gate: launcher and an in-game scene render correctly for 30 minutes on both handheld and docked displays without validation errors, GPU faults, or unbounded memory growth.

### M3 — Complete Switch UX

- Auto-detect the expected ROM filename and show actionable controller-driven errors when it is missing or invalid.
- Supply Switch-first default mappings and verify up to four local controllers, disconnect/reconnect, rumble, and the software keyboard where text entry is unavoidable.
- Make 16:9/720p defaults explicit while retaining RT64 widescreen patches.
- Persist graphics, sound, controls, saves, quicksaves, and mod state.
- Replace desktop-only Install/Open Folder actions with SD-card instructions and a rescan action.
- Handle suspend/resume, HOME, focus loss, dock/undock, and clean shutdown.

Exit gate: the base game is completable with saves, menus, audio, rumble, and supported embedded/SD-card mods.

### M4 — Performance and release parity

- Profile CPU, GPU, memory, SD I/O, and shader/pipeline creation on Erista and Mariko.
- Add persistent pipeline caches and remove first-use stutter.
- Offer 30 fps as the safe baseline; expose 60 fps only after frame pacing and thermal testing.
- Test 720p handheld and 1080p docked scaling. Keep expensive RT64 enhancements off by default.
- Produce a release zip containing only the NRO, open-source assets, controller database, README, and licenses.
- Add CI using the devkitPro image and a hardware smoke-test checklist for releases.

## Feature parity targets

| Area | First playable target | Later target |
| --- | --- | --- |
| Rendering | 720p, 16:9, 30 fps, FIFO | docked scaling, 60 fps where stable |
| Input | one controller, remapping, rumble | four-player, gyro audit |
| Audio | 48 kHz stereo through SDL2 | suspend/resume and latency tuning |
| Storage | ROM/config/save/mod directories on SD | migration and recovery UX |
| Mods | embedded and data-only mods first | live code mods if executable-memory policy permits |
| UI | controller-first launcher/config | Switch keyboard and refined platform prompts |

## Build the current bootstrap

Requirements: devkitA64, libnx, `switch-sdl2`, CMake, and either Ninja or Make.

```sh
./scripts/switch-build.sh bootstrap
```

The output is `build-switch/snowboardkids2-recompiled.nro`. Copy it to the target SD-card directory and launch it through title takeover. A green left status bar means SD-card persistence works; a green right status bar means the process has application-mode memory. Press Plus to exit.

## Build the runtime + NVK hardware probe

The renderer package is pinned to switch-nvk commit
`6eec707da3ad5f86c64f748226583202801bfd03` and Mesa 25.0.7. Its upstream
build currently requires about 15 GB of Docker storage. The project patch also
pins Rust nightly 2026-05-25 so the custom Horizon standard library cannot
silently break as nightly Rust changes.

```sh
./scripts/build-switch-nvk.sh
export SK2_SWITCH_NVK_ROOT="$PWD/build-switch-nvk/source/nvk-switch"
./scripts/switch-build.sh core
```

The output is `build-switch-core/snowboardkids2-core-probe.nro`. Launch it in
application mode. It creates the NVK interface/device, a native VI surface, a
1280x720 three-image swapchain, and presents a green clear through Plume. NVK
is then fully shut down before the libnx console is restored. The final screen
reports `NVK PRESENTATION + CLEAN SHUTDOWN PASS`; press Plus to exit.
Diagnostic output is written to
`sdmc:/switch/snowboardkids2-recompiled/core-probe.log`.

The current hardware-validated path forces switch-nvk's linear CPU-copy WSI
fallback. Its experimental zero-copy `NvGraphicBuffer` registration remains
disabled until it is stable across the supported Horizon/libnx combinations.

## Build the full game

Copy a legally obtained, decompressed NTSC-U 1.1 ROM to the repository root as
`snowboardkids2.z64`. It is ignored by Git and is never included in an NRO or
release archive.

```sh
./scripts/generate-recompiled-code.sh
export SK2_SWITCH_NVK_ROOT="$PWD/build-switch-nvk/source/nvk-switch"
./scripts/switch-build.sh full
```

The expected output is `build-switch-full/snowboardkids2-recompiled.nro`.
The script compiles the MIPS patch payload inside the pinned switch-nvk Docker
image before cross-linking the aarch64 NRO, so it also works on macOS hosts
whose system Clang lacks a MIPS backend.

A ready-to-copy directory containing the NRO, required UI assets, and controller
database is created at
`build-switch-full/sdcard/switch/snowboardkids2-recompiled/`. Add the user-owned
ROM to that directory as `snowboardkids2.z64` before copying it to the SD card.
The same payload is also emitted as `build-switch-full/snowboardkids2-switch-sdcard.zip`
for extraction directly at the SD-card root.

The full game writes crash-surviving startup checkpoints to
`sdmc:/switch/snowboardkids2-recompiled/startup.log`. If the first hardware
boot fails, copy that file back with the probe log before rebuilding.

## Current gates before a playable build

1. Boot the generated full target and validate the first real RT64 game frame.
2. Exercise audio, EEPROM saves, controller mappings, suspend/resume, and memory use in a long gameplay session.
3. Profile the CPU-copy presentation fallback and re-enable zero-copy only after its native buffer registration is stable.
4. Runtime code mods remain intentionally unavailable until a safe Horizon W^X policy is implemented; embedded and data-only mods are the first playable target.

These are engineering gates, not reasons to fork the game logic. The recompiled ARM64 code, SDL audio/input model, assets, configuration system, and most UI/game features remain reusable.
