# Switch Performance settings

Open the white/blue configuration menu with Select/minus, then Performance.
Settings use the existing Apply/Discard behavior and are saved separately in
`sdmc:/switch/snowboardkids2-recompiled/switch_performance.json`.

- **Clock control: System** is the default. Choosing System and Apply releases
  the game's overrides. Custom enables the per-module requests below.
- **CPU** offers only queried supported entries from 1020, 1224, 1326, 1428,
  1581, 1683 and 1785 MHz. CPU and GPU lists use dropdowns when long.
- **GPU** offers queried supported standard rates up to 768 MHz. A saved higher
  request is capped to 460.8 MHz on Erista battery power, 614.4 MHz on Mariko
  battery power, or 768 MHz with supported charging/docked power. The request
  remains saved for a future power-mode change. Unsupported chargers use the
  battery limit. This is a bounded application policy, not a guarantee that a
  particular rate or FPS will suit every device and workload.
- **Memory** offers System or a queried supported 1600 MHz rate.
- **Boost during loading** requests Horizon FastLoad only during startup shader
  creation and paused MSAA warmup. CPU is boosted and GPU reduced behind the
  progress bar. Normal mode and the saved gameplay selection resume afterward.
- **Clock status** and the per-module readouts distinguish ownership, requested
  rates, capped applied rates and observed hardware rates. Readouts do not dirty
  the config or change temporary selections.

## Ownership and errors

The backend uses libnx clkrst on Horizon 8+. Hardware and power classification
must succeed before writes are permitted. Unknown or unavailable services leave
system control active. It applies a complete validated request, verifies readback
and rolls back changes on failure. Failed rollback retains recovery ownership;
select System and Apply to retry restoration. It does not repeatedly force
clocks if another owner changes an applied rate.

An asynchronous read-only worker checks Atmosphere's TIPC HasService extension
and sys-clk API v4's enabled flag. Enabled sys-clk has priority and disables
application OC/FastLoad controls. Disabled sys-clk allows application control.
No sys-clk enable flag, global override or takeover-title profile is modified.
Unknown protocols, IPC errors or responses older than 1.5 seconds block writes.
Temporary unknown ownership preserves restoration records. A focus release
waits for discovery to recover; recovery restores matching old rates before
reapplying the saved selection. Detecting enabled sys-clk relinquishes ownership.
IPC discovery runs outside the render/input threads; a stalled service cannot
block menu refresh or orderly shutdown waiting indefinitely.

Applet hooks flag focus, resume, power-mode and exit changes. A periodic control
pass handles them, polls charger changes and restores/reacquires ownership.
Focus-loss notifications are retained across suspension. Changing power modes
reasserts the current Horizon performance configuration rather than restoring a
stale handheld snapshot after docking. Matching baseline rates are restored on
System selection and orderly exit. A system/external change is respected.
Forced termination cannot execute application cleanup and remains a hardware
validation item.

On Switch, saving closes and checks the temporary file before replacing the
current file through a backup rename. A failed installation restores the old
file; interrupted replacements can recover the backup. The Performance menu
reads the installed JSON back from SD and reports a verification failure when
the saved values differ from the applied selection.

## Validation

`scripts/test-switch-clock-control.py` exercises the production policy and state
machine with ASan/UBSan: supported-rate intersection, invalid saved requests,
power limits, no periodic clock forcing, partial failure, rollback recovery,
readback mismatch, System restoration, CPU-only changes, focus/exit/power events,
and external ownership. `test-switch-fast-load.py` tests the actual scope guard,
delegated ownership, reset retries, fallback service failures and overlapping
scopes. Existing graphics, loading/cache and queue-transaction regressions pass.
`test-switch-settings-save.py` exercises repeated JSON saves, installation and
backup failures, interrupted replacement recovery, and binary-save preservation
against the production file helper with ASan/UBSan.

The full NRO builds with devkitPro. The initial device run identified an incorrect
CMIF ownership query, corrected to Atmosphere's TIPC command. The corrected run
`full-20261007-185115.log` boots, reads clocks, and detects installed sys-clk with
no service error. The first Performance screenshot exposed overlapping radio
labels; subsequent changes use dropdowns and place telemetry beneath controls.
The user confirmed the revised layout is clear. The device detects enabled
sys-clk and permits application control after the user disables it. Readbacks
confirm CPU 1326 MHz, battery-capped GPU 460.8 MHz and memory 1600 MHz. MSAA
warmup releases FastLoad and restores Custom clocks. Startup logs confirm
FastLoad CPU 1785 MHz/GPU 76.8 MHz, followed by normal clocks before gameplay.
The final save was verified on SD in `full-20261007-191906.log`. Relaunch in
`full-20261007-192027.log` loaded Custom CPU 1326 MHz, requested GPU 614.4 MHz,
memory 1600 MHz and loading boost enabled. It applied the battery GPU cap,
temporarily entered FastLoad, and restored all three gameplay rates before
renderer setup completed at 2.574 seconds. Stale discovery after suspension
exposed lost memory restoration records. The controller now preserves them
across unknown discovery, with regression coverage. The subsequent device run
`full-20261007-192314.log` confirmed System restoration to CPU 1020 MHz, GPU
307.2 MHz and memory 1331.2 MHz after HOME. The final run
`full-20261007-192548.log` confirms automatic Custom reapplication after HOME
at 48.417 seconds and full System restoration at 54.241 seconds, with both
saves verified on SD and no clock-service errors. Charger/dock changes and
forced-close behavior remain untested on device.

See [the research](SWITCH_OVERCLOCK_RESEARCH.md) for upstream sources and policy
reasoning. No voltage changes, custom loader patches or higher RAM rates are used.
