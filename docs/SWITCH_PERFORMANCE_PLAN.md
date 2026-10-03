# Switch performance roadmap

Written 2026-10-01. Baseline: `4d03da9`, the hardware-confirmed texture fix.
Implementation started on `codex/switch-performance` on 2026-10-03.
See [implementation results](SWITCH_PERFORMANCE_RESULTS.md) for tested changes,
current measurements, and outstanding release gates. The evidence below
records the original analysis; it is not the current implementation status.

## Progress — 2026-10-03

Implementation checkpoint: `41ee648` on `codex/switch-performance`.

| Area | Current state | Remaining validation |
| --- | --- | --- |
| Audio accounting and continuity | Implemented and host-tested; native SDL buffer handoff repaired; tester confirms continuous sound | Long sessions, latency, suspend/resume |
| Frame/audio measurement | Bounded stage histograms, warm-interval analysis, and presentation FPS counter implemented and hardware-tested | Controlled routes and profiling overhead comparison |
| Texture upload batching | Fenced batches of up to eight images; transfer/draw probes pass; textures remain correct in races | Broader courses/items/menu coverage |
| Asynchronous submissions | Bounded queues, completion/fault handling, and resource-retirement tests; short probe/game runs pass | Opt-in until stress and controlled performance tests pass |
| Framebuffer readback | Cached copy and vector packing enabled by default; byte tests pass; conversion measured at 0.94 ms per copy in the latest race interval | Further copyback/dependency optimization with exact RAM results |
| Combined framebuffer submissions | Opt-in draw/color batching tested with correct sound/textures | No clear FPS gain; retain conservative default |
| Sustained 60 FPS and release gate | Current tester reports about 45 FPS; short runs show correct audio/textures | 30-minute uninterrupted stress test, broader platform tests, consistent 60 Hz pacing |

The accounting fix alone did not repair choppy audio; the native backend
handoff change did. Readback improvements reduced CPU conversion work, but the
latest tests do not prove a controlled FPS speedup or sustained 60 FPS. The
phase descriptions below retain the original proposal; use the table above and
[results](SWITCH_PERFORMANCE_RESULTS.md) for the current state.

## Objective and constraints

Aim for consistently paced 60 Hz output with continuous audio at normal game
speed. Preserve texture correctness, controller responsiveness, saves, and
stable GPU/resource lifetimes. A displayed frame rate alone is insufficient:
measure unique/interpolated frames and duplicated frames separately, and do not
speed up simulation or audio to inflate FPS.

Keep the baseline build available for comparisons and rollback. Make one
behavioral change per commit. Apply dependency changes in disposable sources,
then regenerate the durable patches in `switch/patches/` or
`switch/nvk/switch-nvk-build.patch`. Do not edit generated recompilation output
as the permanent fix.

No console run is needed for the initial analysis, instrumentation, or host
tests. Hardware validation is a later stage.

## Evidence and uncertainty

* The last recorded full-game run lasted 103.7 seconds. Its reported gameplay
  median was 34.83 FPS, with a 26.70 FPS minimum window. These are presentation
  statistics, not a complete CPU/GPU profile.
* The texture fix passed 64 fenced transfer checks and three texture-copy draw
  checks. The user confirmed visibly corrected textures. These checks form the
  correctness baseline for future scheduling changes.
* `queue_samples()` measures output queue duration using the input sample rate.
  The recorded game input was 22,050 Hz; SDL output was 48,000 Hz. This is a
  confirmed accounting error. Its contribution to the audible symptoms still
  needs testing.
* NVK drains the GPU before returning from each execution submission. Decoded
  texture uploads additionally submit/wait separately for each staging copy
  and image copy. Serialization is confirmed; its share of frame time is not.
* The RT64 shader worker requests idle priority, but the Switch priority
  implementation is a no-op. Compilation can compete for CPU time. A previous
  attempt to change the native priority was rejected by Horizon; do not assume
  that a new priority value will work.

## Phase 1 — Correct audio accounting and continuity

Primary files: `src/main/main.cpp`, particularly `queue_samples()`,
`get_frames_remaining()`, `update_audio_converter()`, and `reset_audio()`.
Also inspect N64ModernRuntime's `ultramodern/src/audio.cpp`; it adjusts the
remaining-buffer count again before reporting it to the game.

### 1.1 Fix the queue-duration units

Calculate queued duration from the obtained output format:

```text
output_bytes_per_frame = output_channels * bytes_per_output_sample
queued_seconds = queued_bytes / (output_sample_rate * output_bytes_per_frame)
```

Keep input-domain sample counts separate from output-domain byte counts.
Use wide arithmetic for conversions. At 48 kHz, stereo float output,
38,400 bytes represents 100 ms regardless of the game's input rate.

Today the 22.05 kHz divisor exaggerates queue duration by approximately
2.18 times. The nominal 100 ms sample-skipping threshold therefore activates
at roughly 46 ms of actual buffered output. The code then keeps every second
sample frame, abruptly shortening a chunk without a proper resampling filter.

First commit only the accounting correction and diagnostics. This makes its
effect distinguishable from a later replacement of the catch-up policy.

### 1.2 Replace abrupt catch-up

Measure queue depth and production cadence before selecting a buffer target.
Choose a bounded target with hysteresis rather than repeatedly switching modes
at one threshold. Evaluate gradual rate correction using a stateful resampler
that preserves continuity between chunks. Define a separate recovery policy
for severe backlog; do not apply unbounded exponential sample skipping.

Maintain channel alignment and whole output frames in every path. Audit
frequency changes and ownership of the shared converter so a rate update
cannot race conversion. Audit the two remaining-buffer adjustments before
changing either; they influence how much audio the game decides to generate.

The requested SDL buffer is 256 frames, about 5.3 ms at 48 kHz. Test larger
buffers only after the accounting fix, balancing scheduling tolerance against
input-to-audio latency. Increasing buffer size alone is not the primary fix.

### 1.3 Audio verification

Add host tests for equal and unequal sample rates, queue durations around the
threshold, frame alignment, frequency changes, and chunk-boundary continuity.
Use known waveforms to detect discontinuities introduced by correction.

Extend aggregated diagnostics with minimum/maximum queue depth in actual
milliseconds, production gaps, generated/queued frames, and catch-up events.
Current `empty_before` only samples SDL's queue when the producer runs; zero
does not prove uninterrupted playback. If available in the backend, record
device underruns independently.

Acceptance: no premature sample dropping in host tests; later, continuous
music and effects through race/menu transitions with bounded queue depth and
acceptable latency. A healthy queue log must agree with listening results.

## Phase 2 — Measure the complete frame path

Primary areas: N64ModernRuntime `ultramodern/src/events.cpp`, RT64
`src/hle/rt64_workload_queue.cpp` and `rt64_present_queue.cpp`, texture cache,
shader cache, Plume submissions, and NVK `winsys/drm_shim.c`.

Current `perfFrameStart` begins inside the presentation loop, after earlier
preparation. Its GPU-wait metric is measured after a submission path that has
already blocked for completion. Do not use it to declare the GPU idle or
prove a CPU bottleneck.

Add low-overhead timestamps and counters for:

* VI arrival, workload availability, and presentation completion.
* Display-list preparation, texture decoding, staging/image uploads, and
  framebuffer readback/copyback.
* Submission CPU duration, dependency waits, completion waits, and submits per
  workload/frame. Attribute blocking time inside NVK to the caller.
* Shader compilation duration and periods overlapping active gameplay.
* Queue depth and waits between workload, render, and presentation threads.
* Audio production intervals alongside frame stalls.

Use correlated workload/present IDs and a monotonic clock. Aggregate into
bounded histograms/counters; avoid per-draw logging, allocations in timing
paths, and repeated network writes. Separate cold start from warm gameplay.
Use GPU timestamps only if supported reliably by this driver configuration.

Report p50/p95/p99 frame intervals, missed 16.67 ms deadlines, unique versus
repeated frames, and total wall time. CPU and GPU intervals can overlap, so
do not add their totals as though they were sequential.

Acceptance: a slow frame can be attributed to a specific stage or queue wait,
and instrumentation overhead is checked with an enabled/disabled comparison.
Confirm the configured refresh-rate mode and interpolation behavior before
treating a lower presentation rate as purely a compute problem.

## Phase 3 — Batch texture uploads while retaining fences

Primary area: RT64 `src/render/rt64_texture_cache.cpp`, persisted through
`switch/patches/rt64-switch.patch`.

The current decoded path performs pre-copy transitions, then a staged-buffer
submission and an image-copy submission for each texture, waiting after each.
For N textures, this path can produce approximately `1 + 2N` submissions.

First experiment: batch staging copies for all queued decoded textures, wait
once, then batch image copies and final shader-read transitions, waiting once.
Preserve the separately fenced staging/image boundary that passed the probe.
Do not initially combine everything into one unfenced command stream.

Each in-flight texture needs distinct staging storage or a non-overlapping
slice. The existing reusable staging buffer cannot be overwritten before its
previous contents have been consumed. Keep upload buffers, command lists, and
texture-map publication alive until the corresponding completion fence.
Handle empty and mixed decoded/raw-TMEM queues explicitly.

Acceptance: fewer submits and less upload wall time in a texture-heavy scene;
all baseline transfer/rendering checks still pass; launcher, HUD/item icons,
and world textures remain correct. Track staging-memory high-water usage.
Keep the original path selectable until the batched path passes validation.

## Phase 4 — Introduce bounded asynchronous GPU submission

Primary areas: NVK `winsys/drm_shim.c`, Plume queue/synchronization handling,
and RT64 worker resource reuse.

This is the largest correctness risk. The synchronous drain also masks
resource-lifetime problems and previously protected against channel failures.
Do not simply remove `nvFenceWait()`.

Before changing behavior, audit every assumption that returning from submit
means completion: command buffers, descriptors, upload memory, readbacks,
frame resources, and sync-object queries. Preserve cache maintenance before
work and before completion signaling. Preserve native error detection and
ensure failed work cannot be reported as successfully completed.

Implement an explicit pending-submission queue with owned resources and
completion fences. Distinguish submission availability from completion;
timeline points must retain the correct associated fence. Start with a small,
bounded number of submissions in flight and apply backpressure when full.
Keep the synchronous path as a fallback.

Only wait where a consumer actually needs results or resources are reused.
Drain safely on shutdown and handle timeout, native fault, device loss, and
reset without publishing false completion. Limit experiments initially to
one channel and avoid simultaneous queue-topology changes.

Extend the existing submit/sync host tests to cover pending work, multiple
timeline points, resource retirement, ring saturation, dependency ordering,
failed earlier submissions, reset, and shutdown. The current synchronous
tests are a baseline, not sufficient coverage for the new model.

Acceptance: measurable CPU/GPU overlap and improved frame intervals without
faults, corruption, premature resource reuse, or unbounded memory growth.
Keep asynchronous submission disabled by default until hardware stress
validation passes.

## Phase 5 — Address measured residual costs

Choose these changes from Phase 2 results rather than implementing all of
them speculatively:

* **Shader compilation:** preserve the specialized-shader performance benefit.
  Separate cold compilation, cache loading, and warm play. Consider warming
  known descriptions at loading boundaries or gating background compilation
  when queues/audio indicate pressure. Avoid returning to an always-ubershader
  mode that previously performed poorly.
* **CPU texture decoding:** measure cache hits and decode time. Reuse scratch
  storage, then optimize verified hot formats. Only add NEON paths when scalar
  equivalence can be checked byte-for-byte, including CI/TLUT cases.
* **Framebuffer copyback:** count actual consumers and bytes copied. Coalesce
  or restrict work only when game reads and ordering permit it. Keep CPU
  fallback behavior until an alternative is demonstrated correct.
* **Thread scheduling:** examine contention before changing affinity or
  priority. Respect Horizon's allowed settings and the previous rejected
  priority experiment. Do not move emulated SP/audio tasks to independent
  workers without proving their ordering and completion semantics.
* **Presentation pacing:** once work fits the budget, measure the interaction
  between the explicit 60 Hz sleep and FIFO presentation. If both throttle,
  consolidate pacing around an absolute deadline without removing the
  backpressure that prevents flooding nvservices. Never busy-spin for FPS.

Acceptance for each change: improvement in its measured bottleneck and full
correctness coverage for the affected path. Remove experiments with no clear
benefit.

## Phase 6 — Hardware comparison and release gate

When hardware testing resumes, use `scripts/switch-run.sh 192.168.222.235 full`.
Keep course, character, route, graphics settings, handheld/docked mode, and
clock configuration fixed for each comparison. Test both cold and warm cache
states, documenting which one produced each result.

Use a short repeated course segment for comparisons, then expand to launcher,
file/character selection, race start, dense item effects, pause, results, and
course transitions. Collect R3 captures around affected rendering paths.
Compare several runs, not one unusually fast window.

Final targets:

* Approximately 16.67 ms presentation intervals with few repeated/missed
  frames; report p95/p99 and late-frame rate, not only median FPS.
* Normal simulation and audio speed; interpolation changes must preserve
  game-specific animations, camera behavior, and effects.
* Continuous audio with bounded latency during ordinary play and transitions.
* No GPU faults, texture regressions, or increasing retained memory during a
  30-minute menu/race stress session, followed by broader course/item coverage.
* Reproducible builds, durable patch round trips, and passing submit, sync,
  audio, and log-analysis tests.

If a scene still cannot sustain 60 Hz, document the limiting stage and prefer
an evenly paced fallback over erratic output. Do not label a build stable at
60 FPS on the basis of an average alone.

## Implementation order

1. Audio queue units and targeted host tests.
2. Complete frame/audio instrumentation and baseline measurements.
3. Gradual audio catch-up policy, using the measured queue behavior.
4. Fenced texture-upload batching.
5. Bounded asynchronous submissions, behind a fallback switch.
6. Optimize the remaining measured bottleneck and tune presentation pacing.
7. Controlled comparisons and the long-session release gate.

The first two items can begin without running the game. Later priorities may
change when measurements establish which stage dominates. Stable 60 Hz is a
target, not a promise that these changes alone will achieve it.
