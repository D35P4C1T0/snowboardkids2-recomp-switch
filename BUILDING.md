# Building Guide

For local Switch builds and GitHub release uploads, see
[Publishing a Switch release](#publishing-a-switch-release).

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
cmake -S . -B build/desktop -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang -G Ninja -DCMAKE_BUILD_TYPE=Release # or Debug if you want to debug
cmake --build build/desktop --target SnowboardKids2Recompiled -j$(nproc) --config Release # or Debug
```

## 5. Success

Voilà! You should now have a `SnowboardKids2Recompiled` executable in the build directory! If you used Visual Studio this will be `out/build/x64-[Configuration]` and if you used the provided CMake commands then this will be `build/desktop`. You will need to run the executable out of the root folder of this project or copy the assets folder to the build folder to run it.

> [!IMPORTANT]  
> In the game itself, you should be using a standard ROM, not the decompressed one.

## Local build directories

- `build/desktop/` contains the command-line desktop build.
- `build/tools/` contains host tools used by the Switch build.
- `build/switch/full/` contains the Switch build and SD-card release package.
- `build/switch/{deps,nvk,logs}/` contains patched dependencies, the NVK driver,
  and hardware logs and screenshots.

Regenerate CMake builds in the new locations because caches store absolute paths.
You can move an existing `build-switch-nvk/` to `build/switch/nvk/` and
`build-switch-logs/` to `build/switch/logs/` to reuse them.

## Publishing a Switch release

Build and upload the Switch package from your own machine. No GitHub Actions
secrets or private storage are needed. Set up the local Switch toolchain as
described below, keep Docker running, and install [GitHub CLI](https://cli.github.com/).
Authenticate once:

```sh
gh auth login
```

Commit and push the source you want to release, then run this from the repository:

```sh
./scripts/release-switch.sh v1.0.0-switch.1
```

Replace the example with your chosen release version. The script builds the
full port with that version, packages the accepted optimizations, verifies the
ZIP, then creates a release on the GitHub repository configured as `origin`.
Only `snowboardkids2-switch.zip` is uploaded. The release tag targets the exact
source commit; the script requires that branch to be clean and pushed first.
It refuses to reuse a remote tag pointing at different source. Existing releases
are not overwritten.

The script reuses your installed SDK and NVK package and builds NVK if missing.
Each full build regenerates the game and audio code from your local ROM, keeping
unchanged outputs for incremental compilation. Players download the prebuilt
ZIP and supply their own ROM at runtime.

Optional modes:

```sh
# Upload the exact ZIP already tested on hardware, without rebuilding it.
# Use the ZIP and provenance record produced by a clean build of this commit.
# The tag must match the version embedded in the NRO.
./scripts/release-switch.sh v1.0.0-switch.1 --use-existing

# Build the ZIP for a manual upload; do not contact GitHub.
./scripts/release-switch.sh v1.0.0-switch.1 --build-only

# Create a draft to review before publishing.
./scripts/release-switch.sh v1.0.0-switch.1 --draft

# Mark a release as a prerelease and supply your own Markdown notes.
./scripts/release-switch.sh v1.0.0-switch.1 --prerelease --notes-file release-notes.md
```

Without custom notes, the release includes SD-card setup instructions and the
supported ROM hash. Packaging starts from tracked assets and the current build.
If the previous staging folder contains extra files, the packager preserves it
under `build/switch/full/sdcard-previous-*/` and prints the path. Keep ROMs,
saves and personal settings on your SD card.

## Nintendo Switch homebrew

The full game is hardware-tested with corrected textures and audio and an FPS
counter. The standard graphics configuration keeps framebuffers on the GPU to
target 60 FPS at stock clocks. The long hardware stress test remains open.
See [port status](docs/SWITCH_PORT.md) for the remaining platform work.

With devkitA64, libnx, `switch-sdl2`, Docker (about 15 GB of free storage for
the pinned NVK driver), and your own decompressed NTSC-U 1.1 ROM:

```bash
./scripts/build-switch-nvk.sh
cp /path/to/your/rom.z64 snowboardkids2.z64
export SK2_SWITCH_NVK_ROOT="$PWD/build/switch/nvk/source/nvk-switch"
./scripts/switch-build.sh
```

The build script generates recompiled sources from your ROM, reuses the pinned
switch-nvk Docker image to compile the MIPS patch payload (avoiding Apple Clang,
which has no MIPS backend), builds the NRO, and stages the SD-card package. The
ROM and generated outputs are ignored by Git and are never included in a release
package.

The complete SD-card payload is staged at
`build/switch/full/sdcard/switch/snowboardkids2-recompiled/`. Copy that whole
directory to `sdmc:/switch/`, then add your own ROM as `snowboardkids2.z64`.
The `assets/` directory is required by the launcher and must accompany the NRO.
Alternatively, extract `build/switch/full/snowboardkids2-switch.zip`
directly at the SD-card root; it contains the exact `switch/` hierarchy.
Repackage the current NRO with `python3 scripts/package-switch.py`.

For fast hardware iteration, enter hbmenu through Atmosphere title takeover
(hold R while launching a game), press Y to start NetLoader, then run:

```bash
export SWITCH_IP=192.168.222.235 # Replace with your Switch's NetLoader address.
./scripts/switch-run.sh "$SWITCH_IP"
```

The NRO is uploaded without removing the SD-card payload or ROM. Timestamped
application, RT64, and Plume checkpoints stream to the terminal and are
retained under `build/switch/logs/`, so normal testing no longer requires
copying a log from the SD card. The network writes are nonblocking: a lost or
slow nxlink receiver drops messages instead of freezing a game thread. The NRO
does not create or write `startup.log`; hardware diagnostics are nxlink-only.

To enable the opt-in dev HTTP screenshot server (R3 capture on port 47474),
build and run with `SK2_SWITCH_DEV_SCREENSHOTS=1`. Normal Release builds omit
the screenshot server so R3 keeps its configured game binding.

The full Switch build presents at 1280x720. Graphics settings control the game
render targets: Original uses native resolution, Original 2x doubles it, and
Auto scales for the 720p screen. Downsampling and 2X/4X MSAA selections now reach
the game renderer. Original 2x and live 2X MSAA are confirmed on hardware;
full-game 4X and saved-MSAA startup still need validation. Apply changes
in the graphics menu; MSAA changes recreate
rendering pipelines and can pause while shaders compile. Fresh configurations
default to Original with MSAA None; existing saved selections are honored.
The former `config/force-480p` marker is superseded by Original 2x in the menu.
See [graphics-setting validation](docs/SWITCH_GRAPHICS_SETTINGS.md).

Select/minus → Performance provides supported CPU/GPU/memory requests and
temporary loading boost, with enabled sys-clk taking priority. See
[Performance settings and validation](docs/SWITCH_PERFORMANCE_SETTINGS.md).

Startup and MSAA shader warmup display a centered red loading bar with a white
border. Compiled shaders are cached on SD, and ready pipelines are retained for
each MSAA sample count during a run. First use of an uncached mode can take
longer; known shaders finish warming before gameplay resumes.

After a run, generate a compact performance and failure summary with:

```bash
./scripts/analyze-switch-log.py build/switch/logs/full-YYYYMMDD-HHMMSS.log
```

Add `--csv build/switch/logs/perf.csv` to export the two-second performance
windows for plotting or comparison between builds. Use `--start-seconds` and
`--end-seconds` to compare warm report intervals; faults are still checked
across the complete log. The top-left FPS counter counts completed
presentations, including interpolated frames, rather than simulation ticks.
`--no-fps` hides it, and `--profile` enables detailed timing histograms (off by
default).

Pass diagnostic options through `SWITCH_NRO_ARGS`:

```bash
SWITCH_NRO_ARGS='--profile' ./scripts/switch-run.sh "$SWITCH_IP"
SWITCH_NRO_ARGS='--no-fps' ./scripts/switch-run.sh "$SWITCH_IP"
```

Synchronous GPU submissions, GPU framebuffers, packed framebuffer copyback, and
fused single-pass RAM transfers are enabled by default. Create an empty
`config/force-cpu-copy` file in the SD-card application directory only if you
need the NVK CPU-copy scanout recovery path.

Run all Switch host unit tests with:

```bash
python3 scripts/test-switch.py
```
