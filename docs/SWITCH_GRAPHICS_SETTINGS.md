# Switch resolution and MSAA settings

The Switch graphics menu controls game render targets. The framebuffer shown on
screen remains 1280x720; RT64's VI pass scales the selected game resolution to it.

**Hardware status:** Original 2x and a live change to 2X MSAA are confirmed
working. The isolated 2X/4X draw-and-resolve probe also passed. The loading update
retains ready shaders per sample count: tested None/2X repeat transitions take
approximately one second. First use of an uncached mode still compiles shaders.
Full-game 4X MSAA, saved-MSAA startup and the remaining checklist still need
validation. The replacement candidate addresses an unsafe live-rebuild sequence;
the first candidate's reported failure remains unconfirmed.

## TODO: final validation on Switch hardware

Keep these items open until a real Switch run confirms them. Offline checks do
not complete this validation.

- [x] Run the core `--msaa-probe` and confirm both 2X and 4X draws and resolves
  pass without a GPU fault or crash.
- [ ] Run the full candidate at stock clocks with packed/fused transfers enabled;
  apply None, 2X and 4X MSAA during gameplay and confirm rebuild completion,
  matching target sample counts, visible edge smoothing and no crash or hang.
- [ ] Relaunch with saved 2X and 4X settings and confirm successful startup.
- [ ] Validate Auto resolution and 2x/4x downsampling, including combinations
  with MSAA and a return to Original/None.
- [ ] Capture nxlink logs and compare frame-time spikes and minimum FPS against
  the accepted native-resolution baseline in the same course at stock clocks.
  Record the hardware, clock settings, results and any remaining failures here.

## Settings behavior

| Setting | Game rendering |
| --- | --- |
| Resolution: Original | Native N64 vertical resolution, approximately 240p |
| Resolution: Original 2x | Twice native resolution, approximately 480p |
| Resolution: Auto | Integer scale chosen for the 720p output |
| Downsampling: Off / 2x / 4x | Additional render scale, then downsample to the chosen Original or Original 2x resolution; Auto ignores downsampling |
| MS Anti-Aliasing: None / 2X / 4X | One, two or four samples per game-rendering pixel |

Apply changes using the graphics menu. The implementation supports changes
during play: resolution or downsampling changes invalidate old framebuffers,
and MSAA changes wait for rendering to finish before rebuilding shaders and
render targets. Shader
compilation can pause the renderer during an MSAA change. Saved selections are
used on subsequent launches. Fresh configurations default to Original and None.

## Loading progress and shader reuse

Startup and MSAA changes show a red progress bar on a black background with a
two-pixel white border. At 1280x720 it is 640x30 pixels, centered at (640, 360).
Progress counts completed ubershader pipelines and known specialized shaders;
it is not a time-based estimate. The longest first pipeline can leave the bar
stationary until that unit finishes. Known shader warmup completes before
gameplay resumes, avoiding the immediate burst of background compilation.

The Vulkan cache is stored on SD after warmup and on clean shutdown. Horizon
file replacement keeps a backup until the new cache is installed and recovers
that backup on startup if installation was interrupted. Ready ubershaders and
specialized shaders are also retained separately for each MSAA sample count
for the lifetime of the device, so revisiting a sample count reuses them.
First use of an uncached mode or previously unseen game shaders still requires
compilation; deleting the cache or changing the driver can require rebuilding.

Startup shader creation and MSAA rebuilds request Horizon's temporary FastLoad
CPU boost while rendering is paused behind the progress bar. FastLoad reduces
GPU clocks, so it ends after shader warmup/cache saving and before gameplay
resumes. This uses `appletSetCpuBoostMode`, not custom frequency writes. A
scope guard restores Normal on early returns or exceptions; a failed reset
tries `appletCancelCpuBoostMode` on Horizon 10+ and retries on scope exit.
Unavailable boost services leave loading unchanged. The full game's Performance
controller checks sys-clk's enabled state asynchronously, respects enabled or
unknown external ownership, and restores the saved gameplay clocks after loading.
Standalone probes conservatively skip boosting whenever sys-clk is present.
No gameplay, background shader compilation or in-game loading animation uses
FastLoad. Device logs confirm 1785 MHz CPU and 76.8 MHz GPU during startup,
followed by normal clocks before gameplay. A direct speed comparison remains
unmeasured; the cache timings below predate FastLoad.

The first updated hardware run, `full-20261007-162629.log`, replaced the old
4,896-byte file with a 3,920,484-byte cache after startup warmup, then saved
7,144,828 bytes after the first 2X change. The user confirmed the loading bar
displayed correctly. This cold startup took approximately 46 seconds and the
first uncached 2X change approximately 42 seconds, including specialized
shader warmup previously performed during gameplay. Warm timings are recorded
separately below when available.

In the same run, 2X to None at 332.082 seconds published the replacement
configuration at 333.113 seconds (1.031 seconds), then None to 2X at 337.173
seconds completed at 337.928 seconds (0.755 seconds). Both transitions logged
reuse of ready sample-count pipelines and resumed matching target sample counts.

Final-build warm launch `full-20261007-163509.log` loaded 7,239,164 cache bytes.
Ubershader pipeline 0 returned in approximately 3 ms (1.179 to 1.182 seconds),
shader warmup completed at 2.300 seconds, and RT64 setup completed at 2.303
seconds. The game target was ready at 2.462 seconds. This confirms compiled
shader reuse across launches; the original first pipeline took approximately
24 seconds. Startup used MSAA None, so saved-MSAA startup remains unchecked.

In this final-build warm run, the first None to 2X change after relaunch ran
from 19.458 to 20.675 seconds (1.217 seconds), with ubershader pipeline 0
returning in approximately 1 ms. Returning to None ran from 24.316 to 24.972
seconds (0.656 seconds) and reused ready pipelines. This validates both SD
cache reuse for 2X and the retained native variant. No GPU fault was logged.

Aspect ratio can widen targets, and some framebuffer heights include padding.
For example, an expanded 480p target observed on hardware is 854x480, rather
than the 640x480 target used for a 4:3 image. Resolution changes the game image;
it does not change the fixed 720p launcher/UI render target.

The former `config/force-480p` marker no longer overrides the graphics menu.
Choose Original 2x instead. `SK2_SWITCH_DIAGNOSTIC_NATIVE_RESOLUTION` now only
retains the existing first-native-workload guard/trace; it does not select the
rendering resolution. RGBA8 game color and double-buffered scanout remain the
Switch platform configuration. UI MSAA remains independent and single-sampled.

## Implementation and validation

Previously, the Switch renderer replaced every resolution/downsampling/MSAA
selection with fixed native/no-downsampling/no-AA values after translating the
menu config. Those overrides were removed. RT64's existing configuration
invalidation and multisampling update paths receive the selected settings.
Unsupported MSAA options remain disabled by the existing device capability
checks.

On Switch, an MSAA change drains outstanding workloads and presents, then holds
both queue mutexes throughout shader-cache and render-target replacement. The
new configuration is published only after replacement pipelines are ready.
Previously, the configuration was published before replacement, and the idle
queue locks were released before resource destruction. The new sequence prevents
queue threads from observing partially rebuilt resources. This fixes a code
hazard independently of whether it caused the reported hardware failure.

Packed and fused framebuffer optimizations are still available. Encoded color
copyback resolves multisampled color through RT64 before packing native bytes.
Its resolved-image descriptor is separate from copies which read raw MSAA
images, and is retired when the source textures are released. Packed depth
copyback reads all covered depth samples and packs the closest value, matching
RT64's previous depth-to-color conversion. Reference RGBA8 copyback also uses
this encoding for MSAA depth, avoiding a multisampled-output pipeline bound to
a single-sampled copyback target. Existing completion fences and staging order
are retained.

Checks passed:

- Actual configuration types and production mapping/update methods: all 27
  combinations of Original/Original 2x/Auto, Off/2x/4x downsampling and None/2X/4X
  MSAA; no-op updates, invalidation, scale reporting and shader-rebuild rules.
- Production MSAA replacement method with concurrent observers: both rendering
  queues excluded throughout replacement, configuration published after shader
  readiness, locks released afterward, and unsupported-capability guard retained.
- Production encoded-copy method and texture release under ASan/UBSan:
  single/multisampled color and depth, resolved/raw input views, RG8/RGBA8
  outputs, separate descriptor reuse/retirement, pipeline and sample counts,
  nonzero rows and invalid-range rejection.
- Production pixel shader: all 65,536 native words, 262,144 single-sample depth
  inputs, color dithering and closest-depth selection at 2/4/8 samples.
- Existing framebuffer byte-equivalence and copyback scheduling checks; all
  seven pinned dependency patch round trips; thirteen log-analyzer checks.
- Full game and core-probe Switch NRO builds, including DXC compilation of the
  new multisampled-depth shader and the updated push-constant layout.

These checks validate CPU behavior and compilation; they do not establish that
the Vulkan driver can compile and execute the game's MSAA pipelines.

The tested native-resolution build is preserved at
`build-switch-baseline/stable-0cea74f.nro`. The graphics-settings candidate is
packaged in `build-switch-full/snowboardkids2-switch.zip` with
packed/fused transfers enabled and no ROM included.

## Hardware log

On October 7, 2026, commit `d1481c4` was rebuilt and its core
`--msaa-probe` ran at 10.0.0.56. Log `core-20261007-161004.log` records
successful 17x7 RGBA8 draws, hardware resolves and readbacks at both two and
four samples, each with zero mismatches. Transfer, sampling and batch probes
reported ALL PASS, and presentation reported PASS. Vulkan device and interface
destruction completed before the probe closed its logging socket; the host
then reported a connection reset. No GPU fault was logged. Hardware model and
clock settings were not recorded, and full-game MSAA validation remains open.

Full-game retest `full-20261007-161048.log` launched the same commit with packed
and fused transfers enabled. Applying 2X MSAA at 82.7 seconds drained the queues
and started replacement ubershader pipeline 0 at 82.9 seconds. The user reported
a frozen display and closed the application. Audio/VI checkpoints continued
through 92.1 seconds before the connection reset; no pipeline completion or GPU
fault was logged. This confirms an observed freeze, but the approximately
nine-second compilation observation does not distinguish a hang from a shader
compilation pause. Initial shader setup in this run took approximately 26 seconds.

Retry `full-20261007-161343.log` started with MSAA None, so the closed run had
not persisted 2X. Applying 2X again at 75.7 seconds started pipeline 0 at 75.8
seconds; it returned at 100.0 seconds. Target rebuilding completed at 100.5
seconds, and the actual game target reported two samples at 100.6 seconds.
Rendering resumed after approximately 25 seconds, with later two-second
performance windows around 60 FPS. No GPU fault was logged. This successful
retry is consistent with shader compilation explaining the preceding freeze;
it does not establish the cause of the first candidate's October 6 failure.
The retry also recorded 2x/4x downsampling targets and a return to Original/None,
but visual quality, combinations with MSAA and stock clocks were not verified.

Upload `full-20261006-212929.log` succeeded at 10.0.0.56. Startup reported
programmable sample positions and a maximum of eight samples. Applying Original
2x at 77.3 seconds changed the actual target to 854x480 with vertical scale 2.0
and one sample. Startup had used a 428x241 target at vertical scale 1.0. This
confirms the resolution setting reaches the game target on hardware, matching
the user's observation that Original 2x works.

At 114.9 seconds the user applied 2X MSAA and reported a crash. At 115.1 seconds
the log entered the first MSAA ubershader pipeline compilation. No compilation
completion, MSAA draw, GPU fault or fatal error was recorded before the network
connection reset at 134.2 seconds. Audio/VI checkpoints continued meanwhile.
The initial non-MSAA pipeline compilation had taken 28.3 seconds. The log alone
cannot distinguish slow compilation, a compiler failure, or closure of a frozen
application; the user is away and cannot clarify or retest yet.

The subsequent queue-transaction correction and isolated probe were built
offline. The isolated probe and a live full-game 2X change passed on October 7
as recorded above; the remaining MSAA and downsampling checklist stays open.

When hardware is available, the core probe can test known-input 2X/4X draws and
hardware color resolves without compiling the game's ubershader:

```sh
SWITCH_NRO_ARGS='--msaa-probe' ./scripts/switch-run.sh 10.0.0.56 core
```

Then test the full candidate with None, 2X and 4X MSAA, including changes during
play and relaunch with saved settings. Check rebuild completion and the actual
target sample count in the log. Test Auto resolution and 2x/4x downsampling
separately; Original 2x has already been confirmed.

The log analyzer retains requested settings, device support, rebuild completion
and actual target dimensions/sample counts:

```sh
python3 scripts/analyze-switch-log.py build-switch-logs/full-20261006-212929.log
```
