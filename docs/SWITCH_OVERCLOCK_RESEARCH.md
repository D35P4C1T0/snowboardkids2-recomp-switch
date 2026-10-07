# Switch clock options: research and proposed integration

Researched October 7, 2026. The Performance menu and loading-only FastLoad are
now implemented. See [implementation and validation](SWITCH_PERFORMANCE_SETTINGS.md).
The design discussion below records the research that informed them.

## Recommendation

Add a Switch-only **Performance** tab to the existing Select/minus configuration
modal. Use a small application-owned clock controller backed by libnx `clkrst`
on Horizon 8.0.0 and newer. Default to **System**, meaning the game does not
write clock rates. Keep clock control outside RT64 and the shared frontend.

Use discrete CPU/GPU/memory selections with an Apply button, queried supported
rates, mode-dependent limits and requested-versus-actual clock reporting. If an
active sys-clk manager owns the clocks, show **Managed by sys-clk** and disable
direct writes. A sys-clk adapter can be added separately if editing external
profiles from this menu becomes a requirement.

This provides standalone in-game OC without requiring another sysmodule or
modifying the user's global sys-clk configuration. It also avoids two clock
managers continually overriding one another.

## Sources checked

- [The supplied melonDS-switch repository](https://github.com/melonDS-emu/melonDS-switch),
  branch `switch`, commit `7897bd387bfd37615a049eba28d02dc23cfa5194`.
  Its current tree contains the Qt/SDL frontend and no `src/switch` frontend;
  it does not provide the older clock-control implementation to copy.
- [The historical RSDuck melonDS Switch frontend](https://github.com/RSDuck/melonDS/blob/96c41909fc131d3688c4033f1411ed2f87c50861/src/switch/main.cpp),
  commit `96c41909fc131d3688c4033f1411ed2f87c50861`: a four-entry CPU selector
  at 1020/1224/1581/1785 MHz. `Start` initializes PCV and applies the CPU rate;
  `Pause` requests 1020 MHz and exits PCV. This establishes the simple menu
  pattern, but is a historical reference rather than a modern lifecycle model.
- [libnx clkrst implementation](https://github.com/switchbrew/libnx/blob/master/nx/source/services/clkrst.c):
  initialization checks for Horizon 8.0.0+, and exposes session-based set/get
  clock rate and supported-rate enumeration. The installed SDK has these APIs.
- [libnx performance management](https://github.com/switchbrew/libnx/blob/master/nx/include/switch/services/apm.h):
  FastLoad boosts CPU while throttling GPU. It is unsuitable as a persistent
  gameplay performance preset. Following the research, the renderer now uses
  scoped FastLoad requests during startup shader creation and paused MSAA
  rebuilds, restoring Normal before gameplay. This is separate from the
  persistent Performance menu. See
  `SWITCH_GRAPHICS_SETTINGS.md` for the loading boost's limits and validation.
- [sys-clk clock manager](https://github.com/retronx-team/sys-clk/blob/1fd95096eb08e21e390b50d8cc05223d0ebb6795/sysmodule/src/clock_manager.cpp)
  and [board backend](https://github.com/retronx-team/sys-clk/blob/1fd95096eb08e21e390b50d8cc05223d0ebb6795/sysmodule/src/board.cpp):
  query hardware frequencies, distinguish power profiles/SoC types, cap GPU
  requests, and reset clocks on application/profile changes. Its implementation
  uses clkrst on modern firmware and PCV on older versions.
- [sys-clk client API](https://github.com/retronx-team/sys-clk/blob/1fd95096eb08e21e390b50d8cc05223d0ebb6795/common/include/sysclk/client/ipc.h):
  supports context/frequency queries, overrides and per-title profiles.
  Overrides are module-wide state, not an application-scoped lease. A game
  that is force-closed cannot reliably execute code to remove its overrides.

## Options compared

| Approach | Benefit | Limitation | Decision |
| --- | --- | --- | --- |
| Direct libnx clkrst | Small; already in SDK; no additional installation | Game must implement lifecycle, caps, errors and coexistence | Recommended standalone backend |
| sys-clk IPC | Existing profile handling, telemetry and frequency tables | Requires sysmodule; global overrides can outlive the game; per-title profiles refer to the takeover title | Optional later integration |
| APM FastLoad | Simple CPU loading boost | Throttles GPU; not a CPU/GPU/RAM gameplay control | Exclude from gameplay presets |
| Legacy PCV-only code | Matches historical melonDS implementation | Clock APIs changed with Horizon 8.0.0 | Only an explicit old-firmware fallback |
| Custom loader/voltage patches | Can expose additional hardware rates | Requires a separate platform-specific OC system | Outside this feature |

## Proposed menu

Use the existing white/blue styling and controller navigation.

| Control | Initial behavior |
| --- | --- |
| Clock control | System (default), Custom; report external manager when detected |
| CPU clock | System plus supported entries from 1020/1224/1326/1428/1581/1683/1785 MHz |
| GPU clock | System plus supported entries within the current SoC/power-profile cap |
| Memory clock | System or 1600 MHz, only when supported; no higher RAM rate in the first version |
| Current clocks | Read-only CPU/GPU/memory MHz, separate from selected requests |
| Status | Applied, System managed, externally managed, capped, or service error |
| Apply / Reset | Apply the whole selection; Reset returns ownership to System |

These are proposed limits, not validated performance presets. Query exact Hz
values and intersect them with the supported policy; do not offer every rate
exposed by a modified loader. Avoid rounded MHz as storage/API values.

For the initial GPU policy, upstream sys-clk provides a useful bounded reference:
460.8 MHz for unplugged Erista, 614.4 MHz for unplugged Mariko, 768 MHz for USB
charging. Start with a 768 MHz application ceiling for docked/adequate-power
operation too. Classify hardware and charger state using the services rather
than assuming every original-size Switch is Erista. If classification fails,
leave System active rather than guessing. Higher GPU/RAM rates can remain the
responsibility of an external manager.

CPU clocks may help CPU-heavy compilation and recompilation work; GPU clocks
may help high-resolution/MSAA rendering; memory clocks may help framebuffer
transfers. These are workload-based expectations, not measured FPS gains.

## Integration points in this repository

1. Add `switch/clock_control.h` and `.cpp` for hardware discovery, supported
   rates, readback, limits, acquisition/restoration and serialized application.
   Expose status without leaking libnx handles into menu code.
2. Add `switch/performance_config.cpp` for menu registration. Call
   `recompui::config::create_config_tab("Performance", "switch_performance", true)`.
   Register enum options and a save callback, using the existing config system
   for Apply/Discard and `switch_performance.json` persistence. Ignore temporary
   option-change notifications; apply a complete validated selection together.
3. Register the tab in `src/game/config.cpp::zelda64::init_config()` before
   `recompui::config::finalize()`, guarded by `__SWITCH__`. Configuration loading
   occurs before renderer setup, allowing an explicitly saved Custom setting to
   affect shader warmup as well as gameplay.
4. Wire controller initialization, pending lifecycle updates and clean shutdown
   into `src/main/main.cpp`. `update_gfx()` is an existing main-loop integration
   point. Route work to one controller thread/context; hooks should flag events
   rather than perform blocking service calls inside callbacks.
5. Add the Switch sources to the full-game target in the root `CMakeLists.txt`.
   No RecompFrontend or RT64 patch is required for basic tabs, enum controls,
   disabled options, configuration persistence or callbacks. Rich live telemetry
   can use the existing custom-tab API if needed.

Keep persistent desired settings separate from transient observed clocks and
service status. Validate again after loading the JSON, not only in the menu.
On service failure, retain the last valid state and show the result; do not
abort the game or silently mark an unsuccessful request as applied.

## Clock ownership and lifecycle

- Snapshot rates when acquiring control in the current operation/power mode.
  Apply a validated CPU/GPU/memory request with rollback if a later write fails.
  Read back effective rates and log them with existing performance checkpoints.
- Release overrides on focus loss/HOME, orderly exit and an explicit System
  selection. Reacquire only while foregrounded, after resume and mode changes.
  Use libnx focus/operation/performance/resume hooks plus charger-state updates.
- Do not restore a stale handheld snapshot after docking. If the system has
  already changed a module from the controller's last written rate, relinquish
  that module rather than replacing the new system value with an old snapshot.
- Detect external-manager availability and enabled state with a bounded,
  version-checked probe. Missing service, permissions failure and protocol
  mismatch are different outcomes; do not interpret every failed IPC call as
  proof that no manager exists. Ambiguous ownership leaves System active.
- Do not disable sys-clk globally or rewrite a title-takeover game's profile.
  Do not repeatedly force clocks in a frame loop. Report external changes.
- A forced process termination cannot run cleanup. Validate OS clock reset on
  hardware; ordinary-exit cleanup alone does not prove this behavior.

## Validation before shipping

Native tests should cover rate intersection/caps, invalid saved values,
partial-write rollback, mode/focus transitions, external ownership and readback
errors. Build the full NRO and verify menu Apply/Discard on the device.

Hardware measurements should compare the same course at the same settings with
System clocks, CPU-only, GPU-only and combined changes. Record actual clocks,
SoC, power profile, frame times and temperatures. Also test HOME/resume,
dock/undock, charger removal, normal exit, forced close and relaunch. No OC
performance or lifecycle behavior has been tested by this research turn.
