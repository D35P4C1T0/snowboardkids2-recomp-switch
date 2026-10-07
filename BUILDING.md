# Building Guide

This guide will help you build the project on your local machine. The process will require you to provide a decompressed ROM of the 1.1 US version of the game.

These steps cover: decompressing the ROM, running the recompiler and finally building the project.

## 1. Clone the snowboardkids2-recomp Repository
This project makes use of submodules so you will need to clone the repository with the `--recurse-submodules` flag.

```bash
git clone --recurse-submodules
# if you forgot to clone with --recurse-submodules
# cd /path/to/cloned/repo && git submodule update --init --recursive
```

## 2. Install Dependencies

### Mac

For Mac you will need Xcode installed along with the Metal toolchain:

```bash
xcodebuild -downloadComponent MetalToolchain
```

Along with the following dependencies:

```bash
brew install cmake ninja sdl2 gtk+3 llvm lld
```

### Linux
For Linux the instructions for Ubuntu are provided, but you can find the equivalent packages for your preferred distro.

```bash
# For Ubuntu, simply run:
sudo apt-get install cmake ninja-build libsdl2-dev libgtk-3-dev lld llvm clang
```

### Windows
You will need to install [Visual Studio 2022](https://visualstudio.microsoft.com/downloads/).
In the setup process you'll need to select the following options and tools for installation:
- Desktop development with C++
- C++ Clang Compiler for Windows
- C++ CMake tools for Windows

The other tool necessary will be `make` which can be installe via [Chocolatey](https://chocolatey.org/):
```bash
choco install make
```

## 3. Generating the C code

Now that you have the required files, you must build [N64Recomp](https://github.com/Mr-Wiseguy/N64Recomp) and run it to generate the C code to be compiled. The building instructions can be found [here](https://github.com/Mr-Wiseguy/N64Recomp?tab=readme-ov-file#building). That will build the executables: `N64Recomp` and `RSPRecomp` which you should copy to the root of the snowboardkids2-recomp repository.

After that, go back to the repository root, and run the following commands:
```bash
./N64Recomp us.toml
./RSPRecomp aspMain.us.toml
```

## 4. Building the Project

Finally, you can build the project! :rocket:

On Windows, you can open the repository folder with Visual Studio, and you'll be able to `[build / run / debug]` the project from there.

If you prefer the command line or you're on a Unix platform you can build the project using CMake:

```bash
cmake -S . -B build-cmake -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang -G Ninja -DCMAKE_BUILD_TYPE=Release # or Debug if you want to debug
cmake --build build-cmake --target SnowboardKids2Recompiled -j$(nproc) --config Release # or Debug
```

## 5. Success

Voilà! You should now have a `SnowboardKids2Recompiled` executable in the build directory! If you used Visual Studio this will be `out/build/x64-[Configuration]` and if you used the provided CMake commands then this will be `build-cmake`. You will need to run the executable out of the root folder of this project or copy the assets folder to the build folder to run it.

> [!IMPORTANT]  
> In the game itself, you should be using a standard ROM, not the decompressed one.

## Nintendo Switch homebrew

The full game is hardware-tested with corrected textures and audio, an FPS
counter, and cached/vectorized framebuffer readback. Current races are around
45 FPS; sustained 60 FPS and the long hardware stress gate remain outstanding.
See [tested results](docs/SWITCH_PERFORMANCE_RESULTS.md) for the latest evidence
and [port status](docs/SWITCH_PORT.md) for the remaining platform work.

With devkitA64, libnx, and `switch-sdl2` installed, build the validated SDK/SDL
bootstrap with:

```bash
./scripts/switch-build.sh bootstrap
```

To build the pinned NVK Vulkan driver and the complete runtime/RT64 hardware
probe, Docker and about 15 GB of free storage are also required:

```bash
./scripts/build-switch-nvk.sh
export SK2_SWITCH_NVK_ROOT="$PWD/build-switch-nvk/source/nvk-switch"
./scripts/switch-build.sh core
```

This produces `build-switch-core/snowboardkids2-core-probe.nro`. See
[`docs/SWITCH_PORT.md`](docs/SWITCH_PORT.md) for hardware-test details and the
remaining release gates.

After the bootstrap passes on hardware, generate the game sources from your
own decompressed NTSC-U 1.1 ROM:

```bash
cp /path/to/your/rom.z64 snowboardkids2.z64
./scripts/generate-recompiled-code.sh
export SK2_SWITCH_NVK_ROOT="$PWD/build-switch-nvk/source/nvk-switch"
./scripts/switch-build.sh full
```

The full-build script reuses the pinned switch-nvk Docker image to compile the
MIPS patch payload, which also avoids relying on Apple's Clang (it has no MIPS
backend). The ROM and generated outputs are ignored by Git and are never
included in a release package.

The complete SD-card payload is staged at
`build-switch-full/sdcard/switch/snowboardkids2-recompiled/`. Copy that whole
directory to `sdmc:/switch/`, then add your own ROM as `snowboardkids2.z64`.
The `assets/` directory is required by the launcher and must accompany the NRO.
Alternatively, extract `build-switch-full/snowboardkids2-switch-sdcard.zip`
directly at the SD-card root; it contains the exact `switch/` hierarchy.

For fast hardware iteration, enter hbmenu through Atmosphere title takeover
(hold R while launching a game), press Y to start NetLoader, then run:

```bash
export SWITCH_IP=192.168.222.235 # Replace with your Switch's NetLoader address.
./scripts/switch-run.sh "$SWITCH_IP" full
```

The NRO is uploaded without removing the SD-card payload or ROM. Timestamped
application, RT64, and Plume checkpoints stream to the terminal and are
retained under `build-switch-logs/`, so normal testing no longer requires
copying a log from the SD card. The network writes are nonblocking: a lost or
slow nxlink receiver drops messages instead of freezing a game thread. The NRO
does not create or write `startup.log`; hardware diagnostics are nxlink-only.

During a full NetLoader run, press R3 to capture the next composed frame. The
host watcher started by `switch-run.sh` downloads it automatically to
`build-switch-logs/manual-YYYYMMDD-HHMMSS.jpg` and prints the exact path. R3 is
reserved only while this debug capture server is active; normal SD launches
keep the configured game binding.

The full Switch build presents at 1280x720. Graphics settings control the game
render targets: Original uses native resolution, Original 2x doubles it, and
Auto scales for the 720p screen. Downsampling and 2X/4X MSAA selections now reach
the game renderer. Original 2x is confirmed on hardware; the corrected MSAA
candidate still needs a hardware retest after a reported crash. Apply changes
in the graphics menu; MSAA changes recreate
rendering pipelines and can pause while shaders compile. Fresh configurations
default to Original with MSAA None; existing saved selections are honored.
The former `config/force-480p` marker is superseded by Original 2x in the menu.
See [graphics-setting validation](docs/SWITCH_GRAPHICS_SETTINGS.md).

After a run, generate a compact performance and failure summary with:

```bash
./scripts/analyze-switch-log.py build-switch-logs/full-YYYYMMDD-HHMMSS.log
```

Add `--csv build-switch-logs/perf.csv` to export the two-second performance
windows for plotting or comparison between builds. Use `--start-seconds` and
`--end-seconds` to compare warm report intervals; faults are still checked
across the complete log. The top-left FPS counter counts completed
presentations, including interpolated frames, rather than simulation ticks.
`--no-fps` hides it, and `--no-profile` disables detailed timing histograms.

Pass diagnostic options through `SWITCH_NRO_ARGS`:

```bash
SWITCH_NRO_ARGS='--no-profile --no-fps' ./scripts/switch-run.sh "$SWITCH_IP" full
SWITCH_NRO_ARGS='--async-submissions' ./scripts/switch-run.sh "$SWITCH_IP" full
```

Synchronous GPU submissions and cached readback are the default. Asynchronous
submissions and `--batch-framebuffer-copyback` remain experimental.
`--direct-readbacks` and `--legacy-audio-backend` are comparison controls that
can reduce smoothness or restore choppy sound. See the
[complete option reference](docs/SWITCH_PERFORMANCE_RESULTS.md#profiling-and-comparison-controls).

Audio diagnostics include queue duration, production gaps, catch-up chunks,
SDL/backend failures, and observed empty queues. These counters complement
listening tests; an empty-queue observation alone is not an audible underrun.


The stock-memory bandwidth candidate is available with
`--packed-framebuffer-copyback`. It halves eligible color/depth readback payloads
and commits native bytes directly to RAM. Build normally, then run
`scripts/package-switch.sh --packed-copyback` for a separate SD-card archive
that enables it. `--rgba-framebuffer-copyback` restores reference mode for a
NetLoader comparison. See the [candidate validation and controls](docs/SWITCH_PERFORMANCE_RESULTS.md#2026-10-06--stock-memory-bandwidth-candidate).

The subsequent single-pass RAM transfer candidate adds
`--fused-framebuffer-transfers` to packed copyback. Package it with
`scripts/package-switch.sh --fused-transfers`; compare against
`--staged-framebuffer-transfers` while retaining packed copyback.

The Switch texture uploader copies and flushes active texture bytes when reusing
larger pooled buffers. Profile windows include the worst sample's workload ID
and approximate completion time. The analyzer's `--profiles-csv <path>` option
exports these alongside the timing histograms. Texture traffic counters
compare the active staging payload with retained capacity in the same run.
See `docs/SWITCH_PERFORMANCE_RESULTS.md` for candidate results and their limits.
