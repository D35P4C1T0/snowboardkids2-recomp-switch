# Nintendo Switch port status and plan

## Goal

Produce a native Horizon OS homebrew build of Snowboard Kids 2: Recompiled with the same broad user experience as Ship of Harkinian on Switch: an NRO launched through Homebrew Menu title takeover, controller-first menus, persistent saves/configuration, user-supplied game data on the SD card, mods, widescreen rendering, and stable audio/video pacing.

The port must not contain or download copyrighted game data. Users will copy their own supported Snowboard Kids 2 ROM to the application directory.

## Current status — 2026-10-03

Development branch: `codex/switch-performance`; latest implementation checkpoint:
`41ee648`. The full NRO and SD-card archive build from the pinned dependency
patches. Hardware testing currently uses `192.168.222.235`.

| Area | Tested progress |
| --- | --- |
| Textures | GPU cache-coherency fix passes focused transfer/draw probes; tester repeatedly confirms correct race textures |
| Audio | Queue accounting/continuity and native SDL handoff fixes implemented; tester confirms continuous sound |
| Uploads | Fenced image batching enabled; 64 transfer, 3 draw, and 11 batched-image checks pass |
| Readback | Cached CPU copy and vector pixel packing enabled; byte-equivalence tests pass; latest conversion mean 0.94 ms per copy |
| Performance | Tester reports about 45 FPS; presentation counter visible; detailed stage timing available |
| GPU scheduling | Synchronous default retained; bounded asynchronous and combined draw/color submissions are experimental |

The latest packing build ran for 249.7 seconds without a logged GPU or
audio-backend failure, with correct audio/textures confirmed by the tester.
These short sessions do not establish release readiness or sustained 60 FPS.
The 30-minute stress gate, wider course/item/menu coverage, handheld/docked
tests, save/controller validation, and suspend/resume remain outstanding.
Cold shader/pipeline initialization also remains costly.

See [performance results](SWITCH_PERFORMANCE_RESULTS.md) for measurements,
comparison caveats, build/test commands, and diagnostic flags. The
[performance roadmap](SWITCH_PERFORMANCE_PLAN.md) tracks implemented phases
and remaining work. The dated investigations below preserve earlier evidence;
their historical FPS and audio queue readings are not the current checkpoint.

## GPU coherency investigation — 2026-10-01

The NVK shim constructed a cache-flush command list but did not submit it.
GPU mappings are cacheable even though the CPU mappings are uncached. The
shim now submits cache maintenance before GPU work and before its completion
fence, with a full-engine `SET_REFERENCE` barrier and a separate no-prefetch
command-list boundary. Native channel faults also reject failed work before
its sync objects are published; a reset can advance a syncpoint without
successfully executing the work.

The cache and command-processing boundaries follow the
[deko3d queue/barrier implementation](https://github.com/devkitPro/deko3d/blob/master/source/maxwell/gpu_base.cpp).

Hardware comparison at `10.0.0.107`:

| Check | Before cache fix | After cache fix |
| --- | --- | --- |
| Fenced buffer/image matrix | 63 passed, first 1x1 image readback unchanged | 64 passed |
| RT64 texture-copy draw/readback | First 4x2 readback unchanged; two larger cases passed | All three passed |
| Native surface presentation and cleanup | Passed | Passed |

The matrix covers dedicated and pooled allocations, direct and staged upload,
RGBA8 images from 1x1 through 128x256 including a 285x52 launcher-sized image,
and 4096x1 R8 raw-TMEM storage. The rendering probe uses the existing RT64
fullscreen vertex and texture-copy pixel shaders and compares every output
texel. It does not yet validate RmlUi filtering, N64 decoding, or all game
shader variants.

Evidence is in `build-switch-logs/core-20261001-105947.log` (before) and
`build-switch-logs/core-20261001-110516.log` (after). The earlier inline
upload/readback probe triggered notification 32, a rejected GPU command list.
Full-game diagnostic runs before the cache fix trapped at `NVB197_END`
(`class=0xb197`, `method=0x1614`, `irq=0x00200000`); native error type 2
distinguishes this graphics trap from a page-fault address, despite the outer
notification being 31. These failures were hidden by the old full-game log
filter and completion handling.

The normal core probe tests fenced transfers and texture rendering, then
presentation. Reproduce the fault-prone inline matrix explicitly with:

```sh
./scripts/switch-build.sh core
./scripts/switch-run.sh 192.168.222.235 core
SWITCH_NRO_ARGS='--inline-transfers' ./scripts/switch-run.sh 192.168.222.235 core
python3 scripts/analyze-switch-log.py build-switch-logs/core-YYYYMMDD-HHMMSS.log
python3 scripts/test-switch-submit.py
python3 scripts/test-switch-sync.py
python3 scripts/test-switch-log.py
python3 scripts/test-switch-patches.py
```

The analyzer reports transfers and rendering separately and marks interrupted
suites as incomplete. Host submit tests exercise the actual patched driver
functions, including cache-command ordering and failure publication. Build
scripts preserve the generator of existing CMake trees. The screenshot watcher
now exits on termination, so a closed nxlink connection cannot leave the run
script waiting on an orphaned capture loop.

The rebuilt full game also launched and reached a race in
`build-switch-logs/full-20261001-112145.log`. Over 103.7 seconds, the analyzer
reported a gameplay median of 34.83 FPS, a 27.95 FPS tenth percentile, and a
26.70 FPS minimum window. GPU-wait p95 was 1.28 ms, Vulkan memory peaked at
136 MiB, and audio reported no empty queues or failed submissions. No native
GPU fault or Vulkan fatal was logged before the nxlink connection reset.
The reset alone does not establish whether the game exited normally.

The race-start capture `build-switch-logs/manual-20261001-112314.jpg` shows
legible lap, rank, and coin indicators and coherent character/world textures.
The item slots are empty, so this capture does not validate item icons; it
also does not validate the launcher or other menus. This run used a different
capture scenario from the historical baseline and is not a controlled
performance comparison.

The hardware tester subsequently confirmed that this build fixed the visible
texture corruption and that the game ran smoothly on the Switch. This is a
user-confirmed result for the tested play session; the broader course/menu
matrix and long-duration stress test remain outstanding.

The cache fix has passed the focused hardware probes and this short full-game
run. Longer visual and performance validation is still required before claiming
smooth, glitch-free gameplay or a release-ready build. A thread-priority
experiment was removed after Horizon rejected the requested background
priority (`0xe001`).

## Earlier port status — 2026-08-23

The following completed-work list records the August checkpoint. The backlog
has been annotated with subsequent texture/performance progress; use the
October status above for current measurements and audio validation.

### Working and hardware-tested

- [x] Full aarch64 game runtime builds and packages as a native NRO.
- [x] Homebrew Menu title-takeover launch and SD-card application layout.
- [x] NVK Vulkan surface, fixed 1280x720 FIFO swapchain, and native N64
  internal rendering scaled by the VI pass.
- [x] Switch SDL controller input and 48 kHz stereo audio. Long traces report
  no empty audio queues or failed SDL submissions.
- [x] Controller-first RmlUi launcher with Switch-safe file and mod actions.
- [x] CPU TMEM decoding for the Switch path, including CI/TLUT and RGBA formats.
- [x] Fenced two-stage decoded-texture upload: host-visible buffer to reusable
  device-local buffer, then device-local buffer to sampled image.
- [x] Explicit ARM data-cache clean before NVK consumes mapped upload memory.
- [x] Correct post-copy `SHADER_READ` transitions for game and RmlUi textures.
- [x] Exact merged display-list allocation; HUD-heavy frames no longer overrun
  the frame arena after 14 graphics groups.
- [x] CPU framebuffer color/depth copyback path that avoids unstable Switch
  compute encoders.
- [x] Serialized runtime raster specialization with ubershader fallback.
- [x] Persistent NVK pipeline-cache load/save, live screenshots, timestamped
  hardware logs, submit-history diagnostics, and performance-log analysis.
- [x] NetLoader-only R3 capture workflow: R3 captures the next composed frame,
  the host watcher downloads it automatically, and normal SD launches retain
  the original R3 mapping.
- [x] Best hardware run at the August checkpoint: 145.6 seconds, 30.2 FPS median gameplay,
  healthy audio, 136 MiB peak Vulkan budget use, and no reported Vulkan fatal
  before the title/log connection closed.
- [x] Reproducible dependency patch chain; every follow-up patch passes forward
  and reverse application checks against the pinned submodules.
- [x] Clean dependency workflow: Switch patches are applied to disposable,
  manifest-cached sources under `build-switch-deps/`; canonical submodule
  worktrees remain at their pinned commits.

### Still missing before the port is release-ready

#### P0 — Rendering correctness and stability

- [x] Correct the reported texture corruption with the October GPU cache fix.
  Focused probes pass and the tester confirms correct textures in later races.
- [ ] Complete visual regression coverage of all HUD/item icons, launcher
  buttons, transparent layers, and world effects across multiple courses.
- [ ] Audit the raw-TMEM/S2DEX sampling path separately from decoded textures.
  Moving raw-TMEM images onto the decoded-texture staging strategy was tested
  and rejected because it made HUD corruption worse.
- [ ] Complete a 30-minute uninterrupted race/menu stress test without a
  Vulkan device loss, application exit, or increasing memory use.
- [ ] Validate several courses, characters, weather effects, menus, and all
  item types rather than relying on one representative race.
- [ ] Validate both handheld and docked output on the supported NVK/Horizon
  combination.

### Visual regression coverage

Run each candidate through `./scripts/switch-run.sh <switch-ip> full`. Pause at
each named screen and press R3 once; the host stores timestamped JPEGs under
`build-switch-logs/`.

1. Re-run the durable core transfer/draw/batch probes after changing GPU
   synchronization or cache maintenance. The baseline verifier is implemented
   and passes; extend it for new rendering paths as needed.
2. Capture the launcher after its buttons and version text are visible, then
   file select, title menu, character select, race HUD before item pickup, race
   HUD with an item, pause, and results. Keep one clean reference capture for
   every screen.
3. If uploaded texture bytes differ, isolate the first failing boundary:
   mapped upload buffer, device-local staging buffer, or sampled image. Test a
   dedicated staging allocation before changing shaders or descriptors.
4. If uploaded texture bytes are exact, verify GPU-visible UI vertex/index
   data and RT64 tile metadata next; bad UVs can select coherent but unrelated
   regions from otherwise-correct textures.
5. After the first visual fix, repeat item pickup/use, dialogue glyphs, all
   character portraits, every item icon, and S2DEX-heavy menus on multiple
   courses. Reject fixes that only improve one capture.
6. Run a 30-minute menu/race loop at stock clocks. Require no device loss,
   no growing Vulkan allocation count, continuous sound, and no performance
   regression against the latest roughly 45 FPS checkpoint on the same route.

Rejected diagnostic directions should not be reintroduced without new
evidence: ubershader-only rendering left corruption intact and reduced
gameplay to roughly 7–9 FPS; per-frame descriptor-set recreation left
corruption intact and later lost the device; full upload-buffer cache clean,
raw-TMEM-as-decoded-texture staging, and RGBA/BGRA format substitutions did not
produce a general fix. Texture-cache and tile-copy miss counters also remained
zero in the captured failures.

#### P1 — Performance and frame pacing

- [ ] Reduce cold pipeline initialization; recent runs spend roughly 31 seconds
  in the longest initialization and about 44 seconds across 72 pipelines.
- [x] Improve CPU framebuffer readback with caching and vector packing;
  byte-equivalence tests pass and tested audio/textures remain correct.
- [ ] Improve heavy gameplay beyond the current roughly 45 FPS checkpoint
  while preserving exact framebuffer copyback and normal game/audio speed.
- [ ] Remove runtime pipeline-creation hitches. NVK currently serializes only
  a 4,896-byte cache for this workload, so specialized pipelines still rebuild
  after launch.
- [ ] Measure thermals, clocks, and frame pacing on both Erista and Mariko.
- [ ] Establish sustained 60 Hz presentation with correct interpolation and
  frame pacing. A 60 Hz output target does not imply 60 FPS in races.

#### P1 — Platform and gameplay parity

- [ ] Verify EEPROM saves, configuration persistence, quicksaves, and recovery
  after an interrupted write on real SD cards.
- [ ] Verify controller disconnect/reconnect, remapping, rumble, and four-player
  local play with mixed Joy-Con/Pro Controller configurations.
- [ ] Implement and test suspend/resume, HOME focus changes, dock/undock, and
  clean shutdown during gameplay and saving.
- [ ] Audit every launcher/settings screen for controller-only navigation and
  add a Switch software-keyboard path where text entry is unavoidable.
- [ ] Validate embedded mods, data-only SD mods, enable/disable persistence,
  dependency errors, and malformed-mod recovery.
- [ ] Decide whether live code mods can be supported safely under Horizon W^X
  policy; keep them disabled until that work is complete.

#### P2 — Release engineering

- [ ] Add clean-container CI for patch application, generated code, NRO build,
  packaging, and license collection.
- [ ] Add a repeatable hardware smoke-test checklist and visual-regression
  captures for launcher, title, menus, HUD, and representative courses.
- [ ] Produce a release archive containing only redistributable assets, the
  full NRO, controller database, documentation, and licenses—never game ROMs.
- [ ] Document the pinned switch-nvk build and supported Atmosphere/Horizon
  versions for users and contributors.

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

### Texture-upload reliability (hardware findings)

The Switch CPU TMEM decoder was validated independently against captured CI4,
TLUT, and RGBA output. The remaining horizontal texture corruption came from
NVK's direct host-visible-buffer-to-image path, not the decoder. Tight rows
reduced the damage, but direct copies still produced stale rows and eventually
lost the Vulkan device.

The current candidate uses two fenced transfer stages per decoded texture:

1. host-visible upload buffer to a reusable device-local buffer;
2. device-local buffer to the optimal sampled image, followed immediately by
   the `COPY_DEST` to `SHADER_READ` transition.

Each texture uses its own command list and each stage completes before the next
stage begins. On hardware this removed the large world-texture stripes and
survived 145.5 seconds of active gameplay without a Vulkan fence failure; small
HUD/S2DEX artifacts still require validation, so the 30-minute M2 gate remains
open. RmlUi uploads now also perform the previously missing post-copy shader-read
transition.

The game-side merged display-list patch now allocates exactly
`4 + 3 * graphics_group_count` commands. The former fixed 48-command allocation
overran the frame arena whenever HUD-heavy frames exceeded 14 graphics groups.

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
- Persistent NVK pipeline data is loaded from SD at startup. A cold cache is
  saved atomically only after all eight precompiled ubershader pipelines finish,
  avoiding per-pipeline SD writes while compilation is active.
  Runtime-specialized raster shaders compile serially on one large-stack
  worker while rendering falls back to the precompiled ubershader. The Switch
  worker currently uses the ordinary pthread priority; the background-priority
  request was rejected on hardware.
  Earlier hardware runs reached roughly 37--40 FPS after specialization;
  current tests with cached/vectorized readback report about 45 FPS. NVK currently
  serializes a fixed 4,896-byte cache for this workload, so first-use specialized
  pipeline compilation can still cause visible hitches after every launch.
- Target sustained 60 Hz only after frame pacing and thermal testing establish
  it on hardware; current race output remains around 45 FPS.
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
| Rendering | Fixed 720p FIFO output; roughly 45 FPS in current race tests | sustained 60 FPS, wider docked/handheld validation |
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

Non-bootstrap builds first export the pinned N64ModernRuntime, RecompFrontend,
RT64, and nested submodule commits into the ignored `build-switch-deps/`
directory. The complete Switch patch chain is applied there in strict order,
and CMake builds only from those disposable sources. A manifest reuses the
tree until a dependency commit or patch changes; deleting `build-switch-deps/`
is always safe. The checked-out `lib/*` submodules are never patched in place.

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

On memory-constrained hosts, limit cross-build concurrency, for example:

```sh
export SK2_SWITCH_BUILD_JOBS=2
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
export SWITCH_IP=192.168.222.237
./scripts/switch-run.sh
```

The equivalent explicit form is `./scripts/switch-run.sh 192.168.222.237 full`.

To upload a specific diagnostic or candidate NRO without renaming it:

```sh
./scripts/switch-run.sh build-switch-full/candidate.nro 192.168.222.237
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

While the game is running, fetch the composed 1280x720 frame (including UI)
for visual-regression or texture-glitch inspection with:

```sh
./scripts/switch-screenshot.sh 192.168.222.237 build-switch-logs/capture.jpg
```

The target serves a synchronized renderer readback on TCP port 47474. Omitting
the output argument creates a timestamped JPEG under `build-switch-logs/`.

For rapid manual capture during a full NetLoader run, press R3. The target
captures the next presented frame and `switch-run.sh` automatically saves it
as `build-switch-logs/manual-YYYYMMDD-HHMMSS.jpg`. R3 is reserved and consumed
only while the debug screenshot server is active; a normal SD launch preserves
the game's configured R3 action.

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
the final framebuffer copy-back separately from drawing. Color and depth now
use distinct `FB RDRAM color copyback` and `FB RDRAM depth copyback`
submissions when depth is active; color-only work keeps one submission. Switch
copyback avoids the unstable framebuffer compute encoders: color uses direct
image readback plus CPU RGBA16 packing, while depth is first encoded by the
existing graphics shader into a single-sample RGBA8 target and then follows
the same direct readback path.
Framebuffer contexts include `tz=start/markers/end`, so another timeout names
the exact draw or native copy-back half that hung.

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

The earlier native-resolution diagnostic is now the default rendering path,
with guarded first-workload submissions. The former
`config/diagnostic-native-resolution` marker is no longer needed or read.
`config/force-480p` selects the older 2x internal path for comparison.

The full build attempts NVK zero-copy scanout by default. If that path crashes
on a particular firmware/libnx combination, create this empty recovery marker
and relaunch without rebuilding:

```text
sdmc:/switch/snowboardkids2-recompiled/config/force-cpu-copy
```

Remove the marker to retry zero-copy. CPU-copy is a diagnostic fallback, not a
playable-performance target.

## Current gates before a playable build

1. Fix transparent/generated 2D textures across frontend and in-game HUD
   captures without regressing coherent world textures or stock-clock frame
   rate. Use the `Next texture tests` sequence above.
2. Complete a 30-minute menu/race stress run with no Vulkan device loss,
   increasing allocation count, audio empty queue, or SDL submission failure.
3. Validate EEPROM saves, controller mappings, suspend/resume, HOME focus,
   handheld/docked transitions, and clean shutdown during saving.
4. Validate reconstructed VertexTestZ continuation slices, split color/depth
   render-to-RDRAM copy-back, and zero-copy native-buffer registration across
   several courses and characters. Keep CPU-copy marker testing as recovery
   coverage.
5. Runtime code mods remain intentionally unavailable until a safe Horizon W^X
   policy is implemented; embedded and data-only mods are the first playable
   target.

These are engineering gates, not reasons to fork the game logic. The recompiled ARM64 code, SDL audio/input model, assets, configuration system, and most UI/game features remain reusable.
