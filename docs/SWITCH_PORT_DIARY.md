# Switch port diary

A brief account of the decisions recorded in our commits, from the first Switch
bring-up in August to release preparation in October 2026. We built on the
upstream recompilation, RT64 and RecompFrontend, adapting them for the console.

- **August 4 — Get the native stack running.** We brought up a libnx homebrew
  executable with NVK/Vulkan and the existing renderer. Testing on the Switch
  started with the first presentation path.
  ([81681cc](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/81681cc))

- **August 5–23 — Make rendering dependable.** We bounded GPU work, used native
  internal resolution with 720p output, and repaired texture uploads and TMEM
  handling. We isolated dependency changes in reproducible patches and added
  logs and screenshots to investigate failures on hardware.
  ([7b4ee31](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/7b4ee31),
  [5e98522](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/5e98522))

- **October 1 — Fix the texture corruption.** Explicit GPU cache maintenance
  and fence handling made shared buffers coherent. Transfer probes and gameplay
  checks helped establish that the fix addressed the corruption.
  ([4d03da9](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/4d03da9))

- **October 3 — Repair audio, then measure performance.** We corrected audio
  continuity and native buffer queuing. Frame timings, an FPS counter, cached
  readback and vectorized pixel packing guided optimization; synchronous GPU
  submission remained the default while asynchronous scheduling stayed optional.
  ([22c676d](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/22c676d),
  [41ee648](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/41ee648))

- **October 6 — Reduce memory traffic.** Packed framebuffer readbacks and fused
  transfers reduced copying and bandwidth pressure. We retained reference paths
  for comparison and tested byte equivalence. We also integrated upstream fixes
  and kept Time Trial opt-in.
  ([0cea74f](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/0cea74f),
  [3d0bc7f](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/3d0bc7f))

- **October 7 — Make graphics changes usable.** Resolution and MSAA settings
  reached the renderer through an idle-queue transaction. Shader caching and
  pipeline reuse shortened repeat loads; the red progress bar made compilation
  visible before gameplay resumed.
  ([d1481c4](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/d1481c4),
  [3dc0ba8](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/3dc0ba8))

- **October 7 — Add bounded clock controls.** The Performance menu offered
  supported CPU/GPU/memory rates, power-dependent GPU limits and temporary loading
  boost. We respected enabled sys-clk, verified saved settings, and tested clock
  restoration after loading and HOME/resume.
  ([3dc0ba8](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/3dc0ba8))

- **October 7 — Prepare a simple package.** We made the accepted transfer
  optimizations standard, named the ZIP `snowboardkids2-switch.zip`, added the
  desktop icon to hbmenu, and documented installation and the supported ROM hash.
  Players supply their own ROM; no compilation is required to use the package.
  ([67d28c6](https://github.com/D35P4C1T0/snowboardkids2-recomp-switch/commit/67d28c6))

AI assisted research, implementation, debugging and documentation throughout
these months. Repeated testing on real hardware shaped the decisions above.
