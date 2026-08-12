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
- Use a fixed 1280x720 output surface, native-resolution game render targets
  scaled by the VI pass, RGBA8, FIFO presentation, double buffering, and no MSAA. Both
  the game and RmlUi paths are single-sampled; the frontend no longer creates
  an independent 8x-MSAA 720p target.

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
- Add persistent pipeline caches only after NVK cross-process cache reuse is
  stable. Current builds use a transient in-memory Vulkan pipeline cache: no
  pipeline data is loaded from or saved to SD. Runtime-specialized raster
  shaders are disabled on Switch because hardware traces measured 40 seconds
  of pipeline creation in a 72-second run, including a 30.7-second compile.
  Rendering uses the precompiled ubershader instead.
- Offer 30 fps as the safe baseline; expose 60 fps only after frame pacing and thermal testing.
- Test 720p handheld and 1080p docked scaling. The Switch baseline renders the
  game at native N64 resolution and uses the VI pass for the fixed 720p output.
  The first workload is split into guarded setup/framebuffer submissions. A
  `config/force-480p` marker restores the former 2x internal target for driver
  comparison, but hardware traces show it saturating GM20B/NVK during gameplay.
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

## Live hardware logging

Use Atmosphere title takeover to enter hbmenu, press Y to start NetLoader, then
upload and stream the full build:

```sh
export SWITCH_IP=192.168.1.123
./scripts/switch-run.sh
```

`nxlink -s` receives an explicit checkpoint stream; stdout/stderr are not
redirected because libnx's blocking stdio socket can freeze a render thread
when the host backpressures or disconnects. Network writes are nonblocking and
may drop messages instead. The helper writes each session to
`build-switch-logs/full-YYYYMMDD-HHMMSS.log`. Checkpoints include millisecond
timestamps, and RT64 emits a two-second performance sample containing effective
FPS; average and maximum frame/GPU-wait times; sample count; swapchain extent;
detected F3DEX/S2DEX microcodes; bounded unknown-opcode warnings; framebuffer
batch timings; and periodic Vulkan memory budgets.
On macOS the helper runs nxlink through a PTY, preventing its host-side 16 KiB
buffer from hiding the final lines while a frozen target remains connected.

Summarize a captured run, or export its performance windows for plotting, with:

```sh
./scripts/analyze-switch-log.py build-switch-logs/full-YYYYMMDD-HHMMSS.log
./scripts/analyze-switch-log.py build-switch-logs/full-YYYYMMDD-HHMMSS.log \
  --csv build-switch-logs/perf.csv
```

The summary reports FPS distribution, frame/GPU wait percentiles, pipeline
creation cost, slow render-to-RDRAM submissions, peak device memory, detected
microcodes, audio queue health, warnings, and the final fatal context. Audio
health includes the number of empty queues and failed SDL submissions, current
buffer size/device status, and the peak generated sample value. Older logs
without the new maximum-time or audio-peak fields remain supported.

The 2026-08-11 hardware trace confirmed the fixed 1280x720 FIFO swapchain and
55.53 FPS median after startup, but timed out in the final slice of a
VertexTestZ-heavy render-to-RDRAM pair. The follow-up renderer now recreates the
VertexTestZ compute prepass when a bounded slice begins inside an active range,
bounds-checks off-screen depth probes before loading the depth image, and emits
the final framebuffer copy-back as a separate `FB RDRAM copyback` submission.
Framebuffer contexts include `tz=start/markers/end`, so another timeout can be
attributed to drawing or native copy-back without guessing.

Unknown GBI diagnostics are deduplicated by command words. Each distinct
S2DEX/F3DEX command logs its command address, `w0`, and `w1` once, with sparse
power-of-two occurrence updates. The analyzer groups older repeated warnings,
keeping the summary readable while preserving the words needed to identify the
observed S2DEX2 opcode `0x64`.

The later 2026-08-11 trace identified those `0x64` words as RT64 extended GBI
commands: IDs 7 and 8 are viewport and scissor alignment. RT64 clears the
extended dispatcher at a full sync, while the frame-merging patch previously
re-enabled it only on multi-group frames. Standalone S2DEX/F3DEX tasks now get
their own `gEXEnable` wrapper. A corrected hardware run should therefore have
no unknown `opcode=0x64` warnings; their absence is the validation signal for
the missing menu/sprite fix.

The 2026-08-12 trace validated that dispatcher change—there were no unknown GBI
warnings—and showed healthy continuous audio (`960` queues, no empty queues or
SDL failures, active device, nonzero sample peaks). Gameplay nevertheless fell
to a 3.64 FPS median at the 2x/480p internal target: workload GPU waits reached
165 ms while presentation remained cheap, followed by `VK_ERROR_DEVICE_LOST`.
The default was therefore changed to native-resolution scene rendering while
retaining the 1280x720 swapchain and VI output upscale.

The NRO does not create or write `startup.log`. Switch diagnostics are emitted
only through the nonblocking nxlink checkpoint stream, so logging performs no
SD-card I/O during either network or normal launches.

To diagnose the native-resolution NVK loss without changing the safe default,
create this empty marker and launch through nxlink:

```text
sdmc:/switch/snowboardkids2-recompiled/config/diagnostic-native-resolution
```

This selects 1x and splits only the first workload into setup/RSP and
framebuffer submissions. The live log identifies which half loses the device.
Remove the marker to return to the normal 2x/480p path.

The full build attempts NVK zero-copy scanout by default. If that path crashes
on a particular firmware/libnx combination, create this empty recovery marker
and relaunch without rebuilding:

```text
sdmc:/switch/snowboardkids2-recompiled/config/force-cpu-copy
```

Remove the marker to retry zero-copy. CPU-copy is a diagnostic fallback, not a
playable-performance target.

## Current gates before a playable build

1. Hardware-validate the fixed 720p swapchain, single-sampled UI glyphs,
   deduplicated controller hints, and ubershader-only renderer through every
   frontend and in-game menu.
2. Exercise audio, EEPROM saves, controller mappings, suspend/resume, and memory use in a long gameplay session.
3. Validate the reconstructed VertexTestZ continuation slices, isolated
   render-to-RDRAM copy-back, and zero-copy native-buffer registration through races, menus,
   suspend/resume, and dock changes. Keep CPU-copy marker testing as recovery
   coverage.
4. Runtime code mods remain intentionally unavailable until a safe Horizon W^X policy is implemented; embedded and data-only mods are the first playable target.

These are engineering gates, not reasons to fork the game logic. The recompiled ARM64 code, SDL audio/input model, assets, configuration system, and most UI/game features remain reusable.
