# Switch performance implementation — updated 2026-10-06

Current branch: `codex/switch-port`, based on `074ae38`. Historical performance
branch: `codex/switch-performance`; texture-correct baseline: `4d03da9`;
vector pixel packing checkpoint: `41ee648`.
Hardware: user's Switch at `10.0.0.56`, launched through title takeover
and NetLoader. This page accompanies [the roadmap](SWITCH_PERFORMANCE_PLAN.md).

## Current checkpoint

The latest default includes repaired audio, corrected GPU cache coherency,
fenced texture-upload batching, direct encoded framebuffer packing, cached
raw/depth readback, optimized integer audio RSP, and the presentation FPS
counter. The original memory configuration measured about **45–48 FPS**
in warm race intervals. The user subsequently reported a stable **60 FPS**
after setting memory to **1600 MHz** with manually overridden timings.
This is a user-observed configuration result; the actual clocks/timings were
not captured in the logs. Synchronous GPU submissions remain the
default; asynchronous execution and combined draw/color copyback are opt-in.
The full build and relevant host tests pass. Controlled comparisons isolating
memory frequency from timings, stable 60 FPS at the original configuration,
and the 30-minute hardware stress gate remain unfinished.

## Implemented behavior

* Audio queue duration uses the obtained output rate, channels, and float
  sample size. Remaining samples are converted separately to the game's input
  rate. Conversion and frequency changes share a mutex.
* Switch catch-up uses continuous stereo interpolation with bounded rate
  changes and hysteresis instead of discarding every second/fourth sample.
  Normal playback retains chronological samples across chunk boundaries.
* The local SDL Switch backend submits each native buffer immediately and
  waits for a reusable slot before fetching the next chunk. Two 1024-frame
  S16 buffers replace the fragile 256-frame handoff. The original backend
  waited for a newly queued buffer to reach PLAYING, leaving little scheduling
  margin. Allocation/update errors are checked and memory is freed on close.
  The private ABI is pinned to installed SDL 2.28.5; see
  [backend provenance and upgrade requirements](../switch/sdl2/README.md).
* Decoded texture uploads group up to eight separate command lists per phase.
  Staging is fenced before image copies; publication waits for completion.
  Per-image state and allocation ownership remain intact. An upload of N
  decoded textures needs `1 + 2*ceil(N/8)` submits rather than `1 + 2*N`.
* Framebuffer readback is copied once from uncached GPU-visible memory into a
  reusable cached vector before CPU pixel conversion. Color/depth encoding and
  GPU fences are unchanged. Cached readback is now the default; use
  `--direct-readbacks` for the original path. `--cache-readbacks` explicitly
  selects caching. Byte-for-byte tests cover every supported dither pattern,
  encoded depth, float depth, odd dimensions, row offsets, and buffer reuse.
* Already-encoded RGBA8 pixels use a separate packing helper to retain their
  first two bytes. The Switch compiler vectorizes sixteen-pixel blocks; a scalar
  tail handles smaller counts. Stronger compiler optimization is restricted to
  this helper. Color/depth shader output, RAM byte order, and fences are preserved.
  Tests check packed bytes independently and cover 15/16/17 and 31/32/33-pixel
  boundaries; the built Switch object was checked for vector loads/stores.
* Optional NVK asynchronous execution retains at most two pending submissions
  per channel and eight pending points per synchronization object. Backpressure
  waits for the oldest fence. The first engine bind drains synchronously;
  dependencies still wait on the CPU. Completion checks inspect native faults
  before and after fence polling. The texture cache flush commands are retained.
  Buffer close, CPU preparation, VM unmap/remap, and channel destruction drain
  pending work. Failed drains retain resources until device shutdown.
  **Synchronous execution remains the default pending the stress gate.**

## Measurements and hardware checks

| Test | Evidence | Result |
| --- | --- | --- |
| Baseline synchronous texture probe with batching | `performance-core-live.log` | 64 transfers, 3 draws, 11 batched-image checks passed |
| Initial accounting/continuity build | `full-20261003-125140.log` | Textures correct; user reported audio still choppy |
| Native audio backend build | `full-20261003-131251.log` | User described audio as "flawless"; no logged GPU fault/backend failure during the run |
| Asynchronous texture probe | `performance-async-core-live.log` | 64 transfers, 3 draws, 11 batched-image checks, presentation and cleanup passed |
| Asynchronous full game | `full-20261003-133346.log` | 180.2 s; user reported correct behavior; no logged GPU fault or audio-backend failure |
| Cached framebuffer readback | `full-20261003-134934.log` | 283.1 s; user confirmed smoother output, correct audio and textures; no logged GPU/backend failure |
| Direct-readback comparison | `full-20261003-135758.log` | Deliberately restores the slower path; user noticed reduced smoothness |
| Cached default before vector packing | `performance-default-live.log` | 126 s; cached readback + synchronous GPU; user confirmed smoother play, good audio and textures |
| FPS overlay | `performance-fps-overlay-live.log` | Build passes; 68 s hardware run; counter visible in title and character-selection captures |
| Combined depth-active draw/color copyback | `performance-combined-copyback-live.log` | User confirmed correct audio/textures and unchanged apparent FPS; remains opt-in |
| Detailed framebuffer timing | `performance-framebuffer-phases-live.log` | Default rendering restored; identifies preparation, recording, tile loading, and RAM commit costs |
| Vector pixel packing | `performance-packed-readback-live.log` | User reported about 45 FPS, correct audio/textures; CPU conversion cost fell modestly |

Logs are saved under the ignored `build-switch-logs/` directory. The confirmed
synchronous audio build is preserved as `build-switch-baseline/audio-fixed.nro`;
`texture-fixed.nro` retains the original texture checkpoint.

The native audio run's first 371 seconds reported gameplay median **32.94 FPS**,
p10 **31.20 FPS**, minimum window **22.49 FPS**. Audio production gaps during
steady racing were roughly **17 ms**, compared with gaps up to **83 ms** in the
previous run. The full run includes startup/menu transitions and a **73.87 ms**
maximum production gap; queue range was **0–44.85 ms**, with no catch-up chunks.
Startup queue-empty observations are counted, so they are not audible-glitch
counts. This is evidence of repaired sound, not evidence of 60 FPS.

Aggregate stage means from that run include NVK submission **2.17 ms**,
presentation composition **12.93 ms**, texture decoding **0.04 ms**, and texture
upload **1.47 ms**. These overlapping stages must not be summed as a frame
budget. Scenes and race routes were not controlled across runs; their medians
are not a valid A/B speedup claim. Cold pipeline creation remains expensive.

The asynchronous full run had gameplay median **32.36 FPS**, p10 **25.89 FPS**,
minimum **22.66 FPS**, and lighter windows reaching **60 FPS**. NVK CPU submission
mean fell to about **0.40 ms**, but display-list handling averaged **36.14 ms**.
The user reported correct sound/textures. This short, uncontrolled run does not
prove a race speedup or satisfy the stress gate; asynchronous mode stays opt-in.

The cached run's report interval **80–283 seconds** had presentation FPS
median **45.26**, p10 **41.91**, minimum **40.21**. Framebuffer CPU conversion
mean was **1.18 ms**, including a **0.54 ms** cached copy. Comparing the same
**80–128 second** report range gives:

| Metric | Direct readback | Cached readback |
| --- | --- | --- |
| Presentation FPS median | 32.37 | 43.05 |
| p10 FPS | 26.57 | 41.85 |
| CPU framebuffer conversion mean | 5.09 ms | 1.18 ms |
| Worst-window conversion p99 | 15.00 ms | 2.25 ms |
| Display-list handling mean | 47.27 ms | 32.22 ms |

Both runs used asynchronous submissions, fixed audio, and the FPS overlay. The
user was asked to use the same course, but inputs and exact scenes were not
recorded/replayed. Treat these as observed run results, not a controlled
percentage speedup. The direct comparison is diagnostic and is **not** the
packaged default. The default package before vector packing used cached
readback with the synchronous GPU fallback. Its **80–126 second** report range had median
**44.36 FPS**, p10 **41.06**, and minimum **39.55**. CPU framebuffer conversion
mean was **1.15 ms**; no GPU or audio-backend failure was logged during the
126-second run. The user confirmed smoother play with good audio/textures.
This verifies the packaged default independently of the asynchronous option;
it is not a 30-minute release stress test.

## On-screen counter

A small top-left counter is enabled by default on Switch, independently of
profiling. It counts completed presentations over half-second windows, including
interpolated frames, and does not represent the original simulation tick rate.
The overlay has its own RmlUi context, does not capture input, and uses the
existing single-sampled presentation pass. `--no-fps` hides it for comparisons.
Hardware captures `manual-20261003-134252.jpg` and `manual-20261003-134307.jpg`
show **31.1 FPS** in the title attract scene and **54.0 FPS** in character
selection. These captures do not establish sustained race performance.

## Profiling and comparison controls

Two-second bounded histograms record count, mean, p50, p95, p99, maximum,
16.67 ms deadline misses, and available workload identifiers. Stages cover VI
intervals, audio RSP tasks, display-list handling, workload/present dependency
waits, framebuffer draw/copyback, texture decode/upload, shader compilation,
pipeline creation, graphics worker GPU waits, CPU framebuffer conversion/cache-copy, queue submit, driver lock/submit, and presentation interval.
Native audio feed/starvation/failure are zero-duration event counters.
The cached default run before vector packing measured display-list handling
in its 80–126 second interval
at 33.14 ms, framebuffer drawing at 4.39 ms per submission, and framebuffer
copyback at 2.66 ms per submission. Separate color, depth, combined draw/color,
and draw-only scopes now distinguish the phases within the aggregate scopes.

Presentation classifications distinguish a new workload, an interpolated pass,
and reuse of a workload ID. They are scheduling proxies, not pixel comparisons
or proof that every image is visually unique. CPU timing scopes include their
nested waits; they are not GPU timestamp measurements. Percentiles use 250 us
buckets up to 64 ms; overflow reports a conservative maximum. The log analyzer
reports worst-window p95/p99, not a reconstructed global percentile.

Run a comparison after opening NetLoader, without a TCP port preflight:

```sh
./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--async-submissions' ./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--no-profile --no-fps' ./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--async-submissions --direct-readbacks' ./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--batch-framebuffer-copyback' ./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--legacy-texture-uploads' ./scripts/switch-run.sh 192.168.222.235 full
SWITCH_NRO_ARGS='--legacy-audio-backend' ./scripts/switch-run.sh 192.168.222.235 full
python3 scripts/analyze-switch-log.py build-switch-logs/<run>.log
python3 scripts/analyze-switch-log.py build-switch-logs/<run>.log --start-seconds 80 --end-seconds 180
```

Metric intervals select report timestamps for FPS, stage histograms, and audio
timing; histograms can include the preceding two-second collection window.
Faults, probe results, and other diagnostics still cover the entire log.

Options may be combined. Legacy audio intentionally restores the fragile
handoff for diagnosis. Use the same race route and power/display mode when
comparing. R3 captures remain available through the run script.

`--batch-framebuffer-copyback` is an experimental depth-active framebuffer path.
It appends color conversion/readback to the intact draw command list, reducing
three submissions to two when depth copyback is needed. The existing graphics
depth conversion remains in its own submission, and both CPU readbacks still
wait for GPU completion. The default retains isolated draw/color submissions
because the first hardware comparison did not establish a useful speedup.

The combined path passed a short race test with correct audio/textures and no
logged GPU fault. Its 80–126 second interval measured median **44.66 FPS**
versus **44.36 FPS** for the prior default. The user also observed similar FPS.
This small, uncontrolled difference does not establish a useful speedup, so the
packaged default keeps isolated depth-active drawing and color readback.
Additional scopes measure framebuffer tile loading, preparation, setup, command
recording, the graphics RSP processor, and the complete CPU RDRAM commit. These
scopes overlap existing timers and must not be summed as a frame budget.

The timing build's 80–126 second interval measured CPU conversion at **1.17 ms**
per copy, total CPU RAM commit at **1.22 ms**, framebuffer preparation at
**0.91 ms** per pair, tile loading at **0.50 ms**, command recording at
**0.28 ms**, setup at **0.01 ms**, and graphics RSP descriptor preparation at
**0.02 ms**. Graphics RSP here measures CPU preparation, not GPU execution.
The subsequent packing build's 130–180 second race interval reduced
mean CPU conversion to approximately **0.94 ms** per copy. The user reported
about **45 FPS** with correct audio/textures. Scene routes were not replayed;
the lower conversion cost does not establish a controlled FPS gain. The new
packing helper is enabled in the default package, while combined framebuffer
submissions remain experimental. Sustained race performance is still below
60 FPS. The packing run lasted 249.7 seconds with no logged GPU fault or
audio-backend failure; captures `manual-20261003-142657.jpg` and
`manual-20261003-142753.jpg` show clear racing textures. This is a short hardware
check, not the 30-minute stress gate.

## Build and host validation

Build and package with the existing SDK and NVK package:

```sh
DEVKITPRO=/opt/devkitpro \
SK2_SWITCH_NVK_ROOT="$PWD/build-switch-nvk/source/nvk-switch" \
SK2_SWITCH_BUILD_JOBS=4 ./scripts/switch-build.sh full
```

Output: `build-switch-full/snowboardkids2-recompiled.nro` and
`build-switch-full/snowboardkids2-switch-sdcard.zip`. Supply your supported ROM
as described by the package script.

All these checks pass; GPU-shim tests extract actual production functions and
verify the durable patch matches the disposable source:

```sh
python3 scripts/test-switch-audio.py
python3 scripts/test-switch-audio-backend.py
python3 scripts/test-switch-perf.py
python3 scripts/test-switch-log.py
python3 scripts/test-switch-submit.py
python3 scripts/test-switch-sync.py
python3 scripts/test-switch-async.py
python3 scripts/test-switch-retirement.py
python3 scripts/test-switch-readback-cache.py
python3 scripts/test-switch-patches.py
```

Tests cover queue units, channel alignment, continuity/rate recovery, buffer
prefill/reuse/shutdown/update failure, percentile overflow, interrupted logs,
cache boundaries, native faults despite an advanced syncpoint, binary and
multiple timeline dependencies, lower completed/higher pending points,
query/reset/signal, bounded history saturation, and resource retention after
failed drains. Cached/default/direct framebuffer output is compared byte for
byte against the actual encoder, including dithering and depth edge cases. Hardware probes also validate native presentation cleanup.

Canonical submodules remain pristine. Dependency edits live in reproducible
Switch patches. `scripts/refresh-switch-patch.py <dependency> [new-path ...]`
regenerates each complete text patch against the pinned source; new paths must
be specified explicitly. Do not treat ignored dependency-tree edits as the
permanent implementation.

## Remaining release gates and next work

1. Validate asynchronous execution in full races before changing its default.
   Compare frame intervals and submission wait time on the same route.
2. Run at least 30 minutes of races/menu transitions with captures, track/scene
   changes, and memory monitoring. Verify sound, latency, textures, shutdown,
   and save/controller behavior. A short probe cannot satisfy this gate.
3. Use the expanded VI/RSP/display-list profile to isolate the remaining CPU
   and GPU limits. Compare profiling enabled/disabled to quantify overhead.
4. The packing build's 130–180 second interval measured about **31 ms** per
   display list and **21 ms** per workload, with overlapping CPU/GPU waits.
   Combining depth-active draw/color submissions did not show a clear benefit.
   Use the separate framebuffer scopes to examine remaining copyback and
   dependency waits before changing fences. Preserve exact RDRAM results.
5. Address expensive composition, copyback/dependency waits, and cold shader
   compilation only where measurements show benefit. CPU texture decoding is
   currently too small to justify a broad SIMD rewrite. Cross-channel GPU
   semaphore waits and per-buffer retirement remain future optimizations;
   the current implementation deliberately uses conservative drains.

Stable 60 FPS and the full release stress gate are still unverified.


## 2026-10-06 — Spike investigation on `codex/switch-port`

Fetched `origin` and verified `074ae38` matches `origin/codex/switch-port`.
The existing `full-20261006-190812.log` is a synchronous, zero-copy baseline:
gameplay window median 45.73 FPS, p10 41.93, minimum 34.80. Display-list
processing averages 23.79 ms and peaks at 49.24 ms; shader compilation averages
192.33 ms. Presentation composition includes acquisition, interpolation waits,
rendering, deliberate pacing and scanout, so its 14.93 ms mean does not identify
a rendering bottleneck on its own.

The candidate snapshots profiling histograms under the collection mutex and
formats/sends reports after releasing it. A separate nonblocking report lock
protects the fixed snapshot; producers continue collecting if a prior report
is still in progress. No additional thread or per-sample allocation is needed.
The enabled flag uses atomic reads/writes. A production collector host test
stalls the log sink and verifies eight concurrent producers finish before the
sink is released, preserving all 801 samples in the following report, including a producer
that crosses a second reporting deadline while the first report is stalled.

New presentation histograms separate `present_interpolation_wait`,
`present_acquire`, `present_render` (including command submission),
`present_pacing`, `present_fifo_wait`, and `present_scanout`. Existing aggregate
metrics remain available; nested scopes must not be summed. This candidate
removes collector contention and prepares attribution of the remaining stalls;
it does not establish a speedup or stable 60 FPS without hardware measurement.


Hardware comparisons used the user's ready Switch at `10.0.0.56` with the same
candidate NRO and native internal resolution / 720p zero-copy output:

| 60–96 s report interval | Synchronous | Bounded asynchronous |
| --- | --- | --- |
| Log | `full-20261006-192315.log` | `full-20261006-192531.log` |
| Presentation-window FPS median | 45.05 | 46.08 |
| p10 FPS | 43.19 | 42.91 |
| Minimum window FPS | 42.71 | 40.58 |

The user was asked to repeat the same course section; inputs and scene positions
were not recorded/replayed. These results do not establish a controlled speedup.
The asynchronous run reduces NVK CPU submission cost, but warm display-list
processing still takes roughly 28 ms and completion waits move into other
stages. The lowest-window FPS and p10 do not improve in this comparison.
The user confirmed good audio and correct rendering in asynchronous mode,
with FPS appearing unchanged. Neither mode reaches stable 60 FPS. Both logs
report no audio-backend failure
or native GPU fault in the captured interval. This is a short check, not the
30-minute stress gate; asynchronous submissions remain opt-in.

The NRO and SD-card archive were rebuilt successfully with the configured
`build-switch-full` target and `scripts/package-switch.sh`. The top-level
build wrapper first stopped because the Docker daemon was unavailable for
MIPS patch compilation; the unchanged, previously built MIPS payload was
reused for this C++ runtime/renderer change. Collector, log analyzer,
readback equivalence, patch round-trip, submit, sync, asynchronous history,
and resource retirement host tests pass.


### Combined color/depth copyback experiment

`--batch-color-depth-copyback` preserves the separate depth-active draw and
appends depth conversion/readback and end operations to the color-only
copyback list. One completion fence protects both CPU commits. The existing
isolated mode shares the same depth recording helper, with its original
separate submission. A production schedule host harness checks one depth
recording, no CPU read before completion, color-before-depth RAM commits,
CPU/native encoder fallbacks, and isolated/combined submit counts. The log
analyzer retains the selected copyback/readback modes in its summary.

The first upload (`full-20261006-193120.log`) still issued a duplicate depth
submission. That candidate was corrected and its measurements are excluded.
The corrected run is `full-20261006-193430.log`. The experiment remains opt-in
until measured and visually checked on hardware.

### Direct encoded packing and audio RSP

`--direct-encoded-readbacks` packs the already encoded GPU bytes directly from
the completed mapped readback buffer. It skips the intermediate CPU scratch
copy for that format; raw RGBA and float depth retain the cached path. GPU
completion and unmap behavior are unchanged. The production encoder harness
checks identical output, odd widths and tails, row offsets, dithering, float
depth, bounds, and that the encoded fast path leaves the scratch cache untouched.

The user reported smoother racing and correct audio/textures with this option.
The 120–180 s race interval in `full-20261006-193731.log` measured median 47.67
FPS, p10 43.78, minimum 42.48. CPU encoding averaged about 0.63 ms, compared
with about 0.90 ms in the earlier cached run. Scenes were manually driven;
these are observations, not a controlled overall speedup measurement.

`--optimized-audio-rsp` selects a separately compiled integer audio microcode
translation with `-O3`. Only this translation enables aligned element-zero
LQV/SQV vector loads/stores. Partial, unaligned, and other element accesses
keep the original implementation. Distinct RSP/context type names prevent
linker folding from mixing reference and optimized inline implementations.
No floating-point relaxation is used. The generated microcode harness checks
54 audio tasks across buffer lengths, mix repetitions, and signed gains against
the reference translation, including full RDRAM and DMEM equality. A separate
memory harness checks every vector element, 8192 addresses, signed offsets,
wrapping, and untouched bytes.

The user confirmed correct audio and textures in both audio candidates.
The O3-only run (`full-20261006-194149.log`) observed about 3.93 ms per audio
task; the aligned-vector run (`full-20261006-194625.log`, 80–120 s) observed
about 3.60 ms. The latter interval had median 47.55 FPS, p10 45.27, minimum
44.47. Neither candidate establishes stable 60 FPS or satisfies the release
stress gate.

### Queue contention investigation

The CPU affinity probe (`full-20261006-194930.log`) found the runtime and
renderer threads already allowed on all three application cores (`mask=0x7`).
It changed no affinity. The probe and its startup option were removed.

The next candidate separates queue-lock wait from `vkQueuePresentKHR` time.
`--prioritize-present` gives a presentation already waiting on the shared
Vulkan queue priority over the next ordinary submission. Disabled mode uses
the original native mutex. Both modes preserve exclusive queue access and
GPU completion fences. A production mutex harness checks exclusivity under
eight contending threads, presentation ordering, and subsequent submit progress.
The warm 80–120 s interval in `full-20261006-195846.log` measured median
46.17 FPS, p10 43.24, minimum 42.26. Queue presentation lock wait was about
0.85 ms and the driver call about 3.71 ms; display lists still took roughly
31 ms. The user confirmed correct audio and textures. This does not show a
clear scheduling gain; ordinary queue scheduling remains the default.

Direct encoded packing and optimized audio RSP are now enabled by default.
`--cached-encoded-readbacks` and `--reference-audio-rsp` restore their reference
paths independently. A subsequent default-build run separates texture upload
waits (`framebuffer_texture_wait`) from setup (`framebuffer_prepare_setup`)
inside the existing framebuffer preparation scope. These nested timings must
not be summed with their parent.

The ordinary scheduling default run (`full-20261006-200141.log`, 80–120 s)
had median 47.79 FPS, p10 43.82, minimum 42.86. Preparation setup averaged
0.05 ms; texture upload wait averaged 1.24 ms and peaked at 17.34 ms.
Presentation's driver call averaged 3.63 ms and queue-lock wait 1.28 ms.
This points to upload completion waits as the source of preparation spikes,
not expensive CPU setup. The manually driven comparison does not establish a
controlled scheduling speedup.

`--batch-upload-prefix` is a subsequent experimental upload schedule. It places
the pre-copy transition list before the first staging lists in one submission,
including the prefix in the existing eight-list limit. A completion fence still
precedes every image-copy batch, and another protects resource publication and
reuse after image copies. For 1–7 decoded textures this removes one submission;
at some larger batch boundaries the smaller first batch can increase submission
count. It is opt-in pending hardware evaluation. The production schedule harness
checks 0–33 textures, exact submission counts, the eight-list bound, prefix
ordering, both completion boundaries, and existing batching/legacy fallbacks.

### User memory configuration finding

The user reported that setting memory to 1600 MHz with manually overridden
memory timings effectively locked the game to 60 FPS. This is strong evidence
that the memory subsystem constrains this workload, and is consistent with the
observed benefit from removing the encoded readback scratch copy. Frequency
and timings changed together, so bandwidth, latency, and contention effects
have not been isolated. No software-only stable-60 claim follows from this
result. The next asynchronous hardware comparison and upload-prefix experiment
were held following this report; the prefix candidate has host checks but no
hardware validation and remains disabled by default. Future performance work
should prioritize measured memory traffic and upload/readback costs, comparing
the same build and race route at recorded memory settings.


## 2026-10-06 — Stock-memory bandwidth candidate

The new `--packed-framebuffer-copyback` option uses dedicated `R8G8_UNORM`
copyback targets. R/G contain the two big-endian native bytes, using the same
color encoder and dither coordinates as the reference RGBA8 path. Both color
and depth copyback now transfer **2 bytes/pixel instead of 4**. For example,
a 320x240 slice drops from 307,200 to 153,600 GPU readback bytes. This is a
reduction for eligible copybacks, not an estimate of total system bandwidth.

Depth is encoded with the existing `FloatToDepth16(z, 0)` GPU helper directly
into the two bytes. It avoids expanding depth into RGBA8 color followed by
CPU RGBA16 conversion. The completed mapped bytes go straight to RDRAM via
one bounded `memcpy`, with no pixel packer or scratch vector. Native rendering
resolution, game logic, submission scheduling, completion fences, and fallback
encoders retain their existing behavior. Dedicated targets retain their format
across resize; ordinary render targets retain their original formats.

This candidate is **opt-in pending hardware validation**. Reference mode is
still the normal launch default. To test at stock clocks after entering
NetLoader:

```sh
SWITCH_NRO_ARGS='--packed-framebuffer-copyback' ./scripts/switch-run.sh 10.0.0.56 full
SWITCH_NRO_ARGS='--rgba-framebuffer-copyback' ./scripts/switch-run.sh 10.0.0.56 full
```

Replace the address if necessary. Use the same course, route, power/display
mode, graphics configuration and warm cache state. Check depth occlusion,
world/HUD/item textures, sound, and transitions. R3 captures and nxlink fault
logs remain available. Do not combine asynchronous scheduling or other
experiments during this comparison.

For SD-card launches, an empty file at
`sdmc:/switch/snowboardkids2-recompiled/config/packed-framebuffer-copyback`
enables the candidate. Remove it to restore the reference, or override it
with `--rgba-framebuffer-copyback` through NetLoader. Explicit launch arguments
win over the marker. `scripts/package-switch.sh --packed-copyback` creates
`snowboardkids2-switch-packed-copyback.zip`, including that marker, separately
from the reference package.

Four bounded traffic counters report `framebuffer_gpu_readback`,
`framebuffer_cpu_read`, `framebuffer_ram_write`, and `framebuffer_scratch_copy`.
Each records transfer count and payload bytes over its actual report interval.
The analyzer reports bytes/transfer and MiB/s and supports the same warm time
filters as timing histograms. These are logical payload counters, not memory
controller measurements: they exclude cache-line amplification, GPU target
writes, and unrelated traffic. Missing scratch-copy samples mean no scratch
copy was counted. Producer collection stays allocation-free, and formatting
occurs outside the collection lock. `--no-profile` disables these counters.

Host validation:

* `test-switch-packed-copyback.py` executes the production pixel shader body
  with HLSL interface adapters. It checks all 65,536 native words, all 262,144
  fixed-depth inputs against the prior quantized-color round trip, and color
  dithering/HDR/row coordinates. DXC compiles the unchanged HLSL interface in
  the Switch build; the host harness does not validate NVK execution.
* `test-switch-readback-cache.py` exercises production GPU-copy recording and
  CPU commit methods: exact two-byte footprints, nonzero row offsets, reuse,
  unsupported/MSAA rejection, byte equality, untouched guards, unmap, and no
  scratch mutation, alongside every existing reference mode.
* Profiler tests verify concurrent timing/byte collection during a stalled
  report, disabled counters, exact totals and snapshot reset. Log tests cover
  byte-rate weighting, malformed records and time filtering.
* The core probe accepts `--packed-framebuffer-copyback` to add native-byte
  shader rendering/readback checks for 1x1, 3x3, 285x52 and 320x240 targets,
  including tightly packed odd rows and nonzero source row offsets.

The full game and core-probe NRO builds passed. Both SD-card archives were
verified for ZIP integrity, the exact latest NRO, required assets, the correct
candidate marker, and absence of ROM files. The submit/sync/async/retirement,
copyback/upload scheduling, queue, byte/shader equivalence, profiler, analyzer,
and pinned patch round-trip checks passed.

Both candidate upload attempts (`full-20261006-202045.log` and
`full-20261006-202308.log`) timed out connecting to NetLoader at 10.0.0.56.
The host route used en0 on 10.0.0.67; the second TCP connection remained in
SYN_SENT to the NetLoader port. Neither log contains startup or gameplay
samples. A subsequent upload (`full-20261006-202549.log`) succeeded: startup
confirmed packed RG8 copyback, synchronous submissions and native internal
resolution, and the byte counters are reporting two-byte copyback payloads.
Initial startup/menu samples do not establish a controlled stock-clock race
speedup. Stock-clock 60 FPS and the 30-minute hardware stress gate remain
unverified.


## 2026-10-06 — Packed result and fused RAM-transfer candidate

The user reported better performance with packed RG8 copyback, with perceived
minimums around 48–49 FPS and solid behavior, and requested further reductions
in memory traffic. The 120–145.1 s report interval in
`full-20261006-202549.log` had median **51.74 FPS**, p10 **46.82**, and minimum
**46.30**. These two-second log windows differ from the short-window on-screen
counter. CPU encoding averaged **0.27 ms/copy**, with RAM commit averaging
**0.32 ms**. No GPU fault, fatal error or audio-backend failure was logged in
the 145.1 s run. The user was asked to test at stock settings; actual clocks
were not captured. This manually driven run is not a controlled A/B speedup
or a 30-minute stress result. The original packed NRO is preserved at
`build-switch-baseline/packed-rg8.nro`.

The next candidate is `--fused-framebuffer-transfers`, combined with
`--packed-framebuffer-copyback`:

* Packed GPU readback previously copied native bytes to RDRAM and then read
  and rewrote all complete RAM words to swap their endianness. The candidate
  swaps each loaded word directly into its final RAM destination, removing
  the extra RAM read/write pass. It accepts whole-word, aligned packed slices;
  narrow, odd, partial-word, misaligned and other-format slices retain the
  prior commit path, including its existing tail semantics.
* Framebuffer uploads previously swapped RAM into a cached scratch vector,
  then copied that vector into the mapped staging buffer. Whole-word uploads
  now swap directly into staging and leave the scratch vector untouched.
  GPU staging-to-native copies, descriptors, resource history, dispatches,
  completion fences and cache maintenance stay in their existing order.
* The shared copy/swap helper uses alias-safe word accesses. The built Switch
  object contains 16-byte vector loads, `REV32`, and stores, plus bounded
  scalar tails. It never reads destination memory. No relaxed floating-point
  flags are used.

The new controls are independent and opt-in. Explicit arguments override
SD-card marker files. `--staged-framebuffer-transfers` restores the previous
RAM transfer behavior while retaining packed RG8 output:

```sh
SWITCH_NRO_ARGS='--packed-framebuffer-copyback --fused-framebuffer-transfers' ./scripts/switch-run.sh 10.0.0.56 full
SWITCH_NRO_ARGS='--packed-framebuffer-copyback --staged-framebuffer-transfers' ./scripts/switch-run.sh 10.0.0.56 full
```

`scripts/package-switch.sh --fused-transfers` produces a separate
`snowboardkids2-switch-fused-transfers.zip` with both candidate markers.
Remove `config/fused-framebuffer-transfers` to compare the preceding packed
mode from an SD-card launch; removing `config/packed-framebuffer-copyback`
also restores RGBA8 reference output.

The traffic collector now also reports `framebuffer_cpu_upload`,
`framebuffer_gpu_upload`, `framebuffer_upload_scratch`, and
`framebuffer_ram_swap`. A reference RAM-swap payload represents a read and
rewrite of that byte count; it is not a hardware memory-controller counter.
The collector used eight traffic entries in this candidate; the following texture-transfer candidate expands it to sixteen.

The extended production-method harness compares staged/fused output across
raw color, encoded RGBA8, packed RG8, float depth, all dither modes, odd widths,
nonzero rows, aligned/partial-word sizes, unmap, guards and buffer reuse.
It executes the actual framebuffer commit and upload-wrapper methods and
actual mapped staging write block, checks scratch bypass and rejection without
writes, and compares independent expected byte order. GPU submission scheduling
is unchanged; the schedule/fence and pinned patch round-trip checks passed.
`test-switch-memory-transfers.py --sanitize` also checks all source/destination
alignments from 0–15 bytes, vector/tail boundaries and untouched guards under
AddressSanitizer and UndefinedBehaviorSanitizer.

The fused game NRO compiled and its separate SD-card archive was verified for
integrity, the latest binary, both markers and assets, with no ROM included.
Upload `full-20261006-203651.log` succeeded. Initial logging through 74.1 s
confirmed both modes with no GPU fault or fatal error. Samples reported at/after
50 s averaged 257 us for the fused helper and 258 us for complete RAM commit
(2633 copies). CPU/GPU upload payload counters were present; no scratch-upload
or RAM-swap payload was counted in that initial interval. These initial scenes
are not a controlled comparison with the preceding race, and a stock-clock FPS
gain for this second candidate was not established by those initial scenes.
The user subsequently reported a small improvement but continued spikes.


## 2026-10-06 — Active texture transfers and spike context

The completed fused run (`full-20261006-203651.log`, 201.3 s) had no GPU fault,
fatal error or audio-backend failure. Reports at/after 100 s contain 51 FPS
windows: median **54.07**, p10 **46.72**, minimum **37.43**. The worst interval
ended at 102.0 s. These are two-second report windows across manually driven
scenes; they do not establish an A/B improvement over the preceding run.
Actual clock frequencies were not logged.

In that interval, complete framebuffer RAM commit averaged **0.27 ms** across
11,834 transfers. Individual presentation intervals reached **70.55 ms**;
`present_render` reached **48.67 ms**, `present_dependency` **31.10 ms**,
`framebuffer_texture_wait` **20.21 ms**, and `texture_upload` **12.85 ms**.
These overlapping CPU scopes must not be added together or interpreted as
GPU timestamp measurements. Their maxima can belong to different events.
The new candidate records enough context to locate each stage's maximum.
Baseline FPS and stage-window CSVs are retained in `build-switch-logs/`, and
the preceding fused binary is preserved at `build-switch-baseline/fused-rg8.nro`.

The concrete memory-traffic fix is in the Switch CPU-decoded texture path.
The staging pool retains each slot's largest buffer capacity, but the previous
GPU buffer copy used that capacity for every later texture. A small texture
reusing a large slot therefore copied unused stale bytes. Staging now copies
exactly `width * height * formatSize` bytes, matching the existing tightly packed
image footprint. The same active range is passed to upload-buffer unmap, so
cache cleaning/flushing also excludes unused capacity. Raw TMEM and native
framebuffer uploads now pass their written ranges to unmap as well.

Buffer allocation sizes, lifetimes, staging/image command buffers, barriers,
eight-list batch bound and completion fences remain intact. This correction
applies to Switch uploads regardless of the packed/fused experimental modes.
Its effect depends on the textures and retained slot capacities encountered.

New `texture_cpu_write`, `texture_gpu_staging` and `texture_staging_capacity`
traffic counters use a sixteen-entry bounded collector. The latter records the
payload that the preceding capacity-based copy would have used. The analyzer
reports avoided logical payload and its percentage for matched counter windows,
excluding separate physical reads/writes and cache-line rounding. These are not
hardware bandwidth
counters. Reports with no transfers are omitted, so per-stage rates are weighted
over that stage's active report intervals.

Each timing window now includes `max_id`, `max_age_us` and `interval_ns`.
`max_id` belongs to the largest sample rather than the last sample.
Subtracting the peak age from the logger timestamp estimates completion time;
formatting and collection latency limit precision. Histogram samples, including
concurrent producers during a stalled log sink, still reset only after their
snapshot is retained. No per-draw socket logging or heap allocation was added.

```sh
python3 scripts/analyze-switch-log.py build-switch-logs/full-20261006-205116.log --start-seconds 100 --csv build-switch-logs/active-texture-fps.csv --profiles-csv build-switch-logs/active-texture-profile.csv
```

Validation passed: production texture mapping/staging blocks under ASan/UBSan
with grow/shrink and odd-dimension reuse, unchanged buffer tails, exact cache
ranges, byte equality, traffic totals and barrier order; production framebuffer
commit/upload byte-order and oversized staging ranges; upload prefix scheduling
through 33 textures with all staging/image fences; profiler concurrency and
peak attribution; twelve analyzer tests including legacy logs, missing traffic
lines and CSV; and all seven pinned patch round trips. The full Switch NRO built successfully.
The updated fused SD-card archive passed integrity, latest-binary, candidate
marker and asset checks and includes no ROM.

Hardware upload to `10.0.0.56` succeeded with packed copyback and fused
transfers enabled, logging to `full-20261006-205116.log`. Logging through
92.1 s confirms the new peak-context fields and no GPU fault or fatal error.
The launcher had not reported Start Game, and decoded texture counters had
not appeared; these initial ~60 FPS samples therefore do not measure this
transfer-size correction in gameplay. The user subsequently accepted the
current build and reported smooth gameplay with modest clock increases on a
V1 Switch. That is subjective playtest confirmation; it does not establish a
controlled stock-clock A/B speedup. The accepted NRO remains packaged in
`snowboardkids2-switch-fused-transfers.zip`.
