# Switch resolution and MSAA settings

The Switch graphics menu controls game render targets. The framebuffer shown on
screen remains 1280x720; RT64's VI pass scales the selected game resolution to it.

**Hardware status:** Original 2x is confirmed working. The first candidate
failed when the user applied MSAA. The replacement candidate passes offline
checks and compiles, but has not yet been retested on the Switch. Its changes
address an unsafe live-rebuild sequence; the hardware failure's cause remains
unconfirmed.

## TODO: final validation on Switch hardware

Keep these items open until a real Switch run confirms them. Offline checks do
not complete this validation.

- [ ] Run the core `--msaa-probe` and confirm both 2X and 4X draws and resolves
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
packaged in `build-switch-full/snowboardkids2-switch-fused-transfers.zip` with
packed/fused transfers enabled and no ROM included.

## Hardware log

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
offline. Their hardware results, plus downsampling results, remain pending.

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
