# Switch audio backend override

These files are adapted from devkitPro SDL commit
`0738d3c9f6993875e2f3dd0e8cc0bb4ae4440b4e` (Switch SDL 2.28 branch):
[original backend](https://github.com/devkitPro/SDL/blob/0738d3c9f6993875e2f3dd0e8cc0bb4ae4440b4e/src/audio/switch/SDL_switchaudio.c).
The upstream zlib notices are retained. This is an altered version.

The game links its own `SWITCHAUDIO_bootstrap` before the static SDL archive.
SDL continues to handle queueing and float-to-S16 conversion; the override
changes the native buffer handoff. Playback queues immediately, then waits for
a reusable slot before the next SDL callback. It does not wait for the newly
queued buffer to become PLAYING. Two 1024-frame native buffers provide room
for the audio renderer's update cadence. Allocation and update failures are
checked, and the native memory pool is freed on close.

The private interface is limited to the installed SDL **2.28.5** ABI, with a
compile-time version check and device-layout assertion. Revalidate against
the actual library before upgrading SDL; do not bypass the guards.
The SDK library is not modified. `--legacy-audio-backend` restores the original
buffer handoff and small requested buffer for comparison.

Profiler event counts `audio_backend_feed`, `audio_backend_starved` (both native
slots reusable after startup), and `audio_backend_failure` distinguish native
buffering from the producer's SDL queue measurements. A starved-slot event is
an observed empty native queue, not an exact count of audible discontinuities.

Run `python3 scripts/test-switch-audio-backend.py` for the production handoff
tests, then validate music/effects and latency on hardware.
