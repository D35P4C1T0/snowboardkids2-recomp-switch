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
brew install cmake ninja sdl2 gtk+3 lld
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

## Nintendo Switch port

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
remaining playable-build gates.

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
export SWITCH_IP=192.168.1.123
./scripts/switch-run.sh
```

The NRO is uploaded without removing the SD-card payload or ROM. Timestamped
application, RT64, and Plume checkpoints stream to the terminal and are
retained under `build-switch-logs/`, so normal testing no longer requires
copying a log from the SD card. The network writes are nonblocking: a lost or
slow nxlink receiver drops messages instead of freezing a game thread. The NRO
does not create or write `startup.log`; hardware diagnostics are nxlink-only.
