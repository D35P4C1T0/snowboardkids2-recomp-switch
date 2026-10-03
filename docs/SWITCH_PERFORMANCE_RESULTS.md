# Switch performance implementation — 2026-10-03

Branch: `codex/switch-performance`. Texture-correct baseline: `4d03da9`.
Hardware: user's Switch at `192.168.222.235`, launched through title takeover
and NetLoader. This page accompanies [the roadmap](SWITCH_PERFORMANCE_PLAN.md).

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
| Final default package | `performance-default-live.log` | 126 s; cached readback + synchronous GPU; user confirmed smoother play, good audio and textures |
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
packaged default. The final default package uses cached readback with the
synchronous GPU fallback. Its **80–126 second** report range had median
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
The final default run's 80–126 second interval measured display-list handling
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
4. The cached default still spends about **33 ms** per display list and
   **20 ms** per workload in the recorded warm interval, with overlapping CPU
   and GPU waits. Next, isolate required color/depth copyback from redundant
   synchronization before removing fences. Preserve exact RDRAM results.
5. Address expensive composition, copyback/dependency waits, and cold shader
   compilation only where measurements show benefit. CPU texture decoding is
   currently too small to justify a broad SIMD rewrite. Cross-channel GPU
   semaphore waits and per-buffer retirement remain future optimizations;
   the current implementation deliberately uses conservative drains.

Stable 60 FPS and the full release stress gate are still unverified.
