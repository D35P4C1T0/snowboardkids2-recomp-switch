#!/usr/bin/env python3
"""Summarize Snowboard Kids 2 Switch nxlink performance logs."""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path


TIMESTAMP_RE = re.compile(r"\[\s*(?P<ms>\d+) ms\]\s*(?P<message>.*)")
PERF_RE = re.compile(
    r"perf: (?P<fps>[\d.]+) fps, frame (?P<frame>[\d.]+) ms, "
    r"acquire (?P<acquire>[\d.]+) ms, present (?P<present>[\d.]+) ms, "
    r"GPU wait (?P<gpu>[\d.]+) ms"
    r"(?:, max frame (?P<max_frame>[\d.]+) ms, max GPU wait (?P<max_gpu>[\d.]+) ms, samples (?P<samples>\d+))?"
)
SLOW_FB_RE = re.compile(r"slow: (?P<context>FB RDRAM .*) (?:wait|total)=(?P<wait>[\d.]+) ms")
MEMORY_RE = re.compile(
    r"plume memory: submit=(?P<submit>\d+) usage=(?P<usage>\d+) MiB "
    r"budget=(?P<budget>\d+) MiB allocations=(?P<allocations>\d+) MiB "
    r"blocks=(?P<blocks>\d+) MiB count=(?P<count>\d+)"
)
UNKNOWN_GBI_RE = re.compile(
    r"warning: unknown GBI opcode type=(?P<type>\d+) opcode=(?P<opcode>0x[0-9A-Fa-f]+) "
    r"dl=(?P<dl>0x[0-9A-Fa-f]+)(?P<detail>.*?)(?: count=(?P<count>\d+))?$"
)
AUDIO_FIRST_RE = re.compile(
    r"audio: first queue .* result=(?P<result>-?\d+) status=(?P<status>\d+) "
    r"queued=(?P<queued>\d+)(?: peak=(?P<peak>\d+))?"
)
AUDIO_HEALTH_RE = re.compile(
    r"audio: health queues=(?P<queues>\d+) empty_before=(?P<empty>\d+) "
    r"failures=(?P<failures>\d+) queued=(?P<queued>\d+) status=(?P<status>\d+) "
    r"peak=(?P<peak>\d+)"
)


@dataclass
class PerfSample:
    timestamp_ms: int
    fps: float
    frame_ms: float
    acquire_ms: float
    present_ms: float
    gpu_wait_ms: float
    max_frame_ms: float | None
    max_gpu_wait_ms: float | None
    samples: int | None


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def parse_log(path: Path) -> dict[str, object]:
    perf: list[PerfSample] = []
    slow_framebuffers: list[tuple[float, str]] = []
    pipeline_times: list[int] = []
    pipeline_start_ms: int | None = None
    memory: list[dict[str, int]] = []
    fatals: list[str] = []
    warnings: list[str] = []
    driver_faults: list[str] = []
    transfer_results: list[str] = []
    transfer_started = False
    transfer_status: str | None = None
    sampling_started = False
    sampling_status: str | None = None
    sampling_results: list[str] = []
    modes: list[str] = []
    pipeline_cache_state: str | None = None
    pipeline_cache_saved: str | None = None
    swapchains: list[str] = []
    ucodes: list[str] = []
    audio_first: dict[str, int] | None = None
    audio_health: list[dict[str, int]] = []
    profiles: list[dict[str, object]] = []
    traffic: list[dict[str, object]] = []
    audio_timing: list[dict[str, int]] = []
    batch_results: list[str] = []
    batch_status: str | None = None
    batch_started = False
    game_start_ms: int | None = None
    duration_ms = 0

    for raw_line in path.read_text(errors="replace").splitlines():
        timestamp_match = TIMESTAMP_RE.search(raw_line)
        # Core-probe logs have no timestamps; retain their transfer failures,
        # native faults and fatal context just like full-game logs.
        timestamp_ms = int(timestamp_match.group("ms")) if timestamp_match else 0
        duration_ms = max(duration_ms, timestamp_ms)
        message = timestamp_match.group("message") if timestamp_match else raw_line.strip()
        message = message.removeprefix("[nvk] ")
        if message.startswith("profile: stage="):
            values = dict(re.findall(r"(\w+)=([\w.-]+)", message))
            required = {'stage', 'count', 'mean_us', 'p50_us', 'p95_us', 'p99_us', 'max_us', 'late', 'id'}
            if required <= values.keys() and all(values[key].isdigit() for key in required - {'stage'}):
                sample = {**{key: values[key] if key == 'stage' else int(values[key]) for key in required},
                          'timestamp_ms': timestamp_ms}
                for key in ('max_id', 'max_age_us', 'interval_ns'):
                    if key in values and values[key].isdigit():
                        sample[key] = int(values[key])
                # The logger timestamp follows the snapshot. This reconstructs
                # a peak's approximate completion time, not a GPU timestamp.
                if 'max_age_us' in sample:
                    sample['max_end_ms'] = timestamp_ms - sample['max_age_us'] / 1000
                profiles.append(sample)
        if message.startswith("traffic: stage="):
            values = dict(re.findall(r"(\w+)=([\w.-]+)", message))
            required = {'stage', 'count', 'bytes', 'interval_ns', 'id'}
            if required <= values.keys() and all(values[key].isdigit() for key in required - {'stage'}) and int(values['interval_ns']) > 0 and int(values['count']) > 0:
                traffic.append({**{key: values[key] if key == 'stage' else int(values[key]) for key in required},
                                'timestamp_ms': timestamp_ms})
        if message.startswith("audio: timing "):
            values = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", message)}
            if {"min_us", "max_us", "gap_us", "input_frames", "output_frames", "corrections"} <= values.keys():
                audio_timing.append({**values, 'timestamp_ms': timestamp_ms})
        if message.startswith("batch probe:"):
            batch_started = True
            if message.endswith(("ALL PASS", "FAILED")):
                batch_status = "passed" if message.endswith("ALL PASS") else "failed"
            elif re.search(r"\b(?:PASS|FAIL)\b", message):
                batch_results.append(message)
        if message.startswith("NVK ") and (
            "FAILED" in message or message.startswith((
                "NVK channel fault:", "NVK native fault:", "NVK fault words[",
                "NVK page fault:", "NVK method fault:", "NVK command fault:"))
            or re.search(r"notification=[1-9]", message)
        ):
            driver_faults.append(message)
        if message.startswith("transfer probe:"):
            transfer_started = True
        if message in ("transfer probe: ALL PASS", "transfer probe: FAILED"):
            transfer_status = "passed" if message.endswith("ALL PASS") else "failed"
        elif message.startswith("transfer probe:") and re.search(r"\b(?:PASS|FAIL|FAILED)\b", message):
            transfer_results.append(message)
        if message.startswith("sampling probe:"):
            sampling_started = True
        if message in ("sampling probe: ALL PASS", "sampling probe: FAILED"):
            sampling_status = "passed" if message.endswith("ALL PASS") else "failed"
        elif message.startswith("sampling probe:") and re.search(r"\b(?:PASS|FAIL|FAILED)\b", message):
            sampling_results.append(message)

        if message == "launcher: Start Game selected":
            game_start_ms = timestamp_ms

        perf_match = PERF_RE.search(message)
        if perf_match is not None:
            perf.append(
                PerfSample(
                    timestamp_ms=timestamp_ms,
                    fps=float(perf_match.group("fps")),
                    frame_ms=float(perf_match.group("frame")),
                    acquire_ms=float(perf_match.group("acquire")),
                    present_ms=float(perf_match.group("present")),
                    gpu_wait_ms=float(perf_match.group("gpu")),
                    max_frame_ms=float(perf_match.group("max_frame")) if perf_match.group("max_frame") else None,
                    max_gpu_wait_ms=float(perf_match.group("max_gpu")) if perf_match.group("max_gpu") else None,
                    samples=int(perf_match.group("samples")) if perf_match.group("samples") else None,
                )
            )

        slow_match = SLOW_FB_RE.search(message)
        if slow_match is not None:
            slow_framebuffers.append((float(slow_match.group("wait")), slow_match.group("context")))

        if message == "rt64 raster: device pipeline creation entered":
            pipeline_start_ms = timestamp_ms
        elif message == "rt64 raster: device pipeline creation returned" and pipeline_start_ms is not None:
            pipeline_times.append(timestamp_ms - pipeline_start_ms)
            pipeline_start_ms = None

        memory_match = MEMORY_RE.search(message)
        if memory_match is not None:
            memory.append({key: int(value) for key, value in memory_match.groupdict().items()})

        if message.startswith("fatal:"):
            fatals.append(message)
        elif message.startswith("warning:"):
            warnings.append(message)

        if (
            message.startswith("startup:") and message.endswith("selected")
            or "ubershaders only" in message
            or message.startswith("rt64 texture cache:")
        ):
            modes.append(message)
        if message.startswith("plume: Vulkan pipeline cache"):
            if "saved bytes=" in message:
                pipeline_cache_saved = message
            else:
                pipeline_cache_state = message
        if message.startswith("plume swapchain:"):
            swapchains.append(message)
        if message.startswith("rt64 gbi:"):
            ucodes.append(message)

        audio_first_match = AUDIO_FIRST_RE.search(message)
        if audio_first_match is not None:
            audio_first = {
                key: int(value)
                for key, value in audio_first_match.groupdict().items()
                if value is not None
            }
        audio_health_match = AUDIO_HEALTH_RE.search(message)
        if audio_health_match is not None:
            audio_health.append({key: int(value) for key, value in audio_health_match.groupdict().items()})

    return {
        "duration_ms": duration_ms,
        "perf": perf,
        "profiles": profiles,
        "traffic": traffic,
        "audio_timing": audio_timing,
        "batch_results": batch_results,
        "batch_status": batch_status or ("incomplete" if batch_started else None),
        "slow_framebuffers": slow_framebuffers,
        "pipeline_times": pipeline_times,
        "memory": memory,
        "fatals": fatals,
        "warnings": warnings,
        "driver_faults": driver_faults,
        "transfer_results": transfer_results,
        "transfer_status": transfer_status if transfer_status else ("incomplete" if transfer_started else None),
        "sampling_status": sampling_status if sampling_status else ("incomplete" if sampling_started else None),
        "sampling_results": sampling_results,
        "modes": list(dict.fromkeys(modes)),
        "pipeline_cache_state": pipeline_cache_state,
        "pipeline_cache_saved": pipeline_cache_saved,
        "swapchains": list(dict.fromkeys(swapchains)),
        "ucodes": list(dict.fromkeys(ucodes)),
        "audio_first": audio_first,
        "audio_health": audio_health,
        "game_start_ms": game_start_ms,
    }


def select_metrics(data: dict[str, object], start_seconds: float, end_seconds: float | None) -> None:
    """Restrict sampled metrics while preserving every fault and diagnostic."""
    if not math.isfinite(start_seconds) or start_seconds < 0 or (end_seconds is not None and
        (not math.isfinite(end_seconds) or end_seconds < start_seconds)):
        raise ValueError("Metric interval must have 0 <= start <= end")
    start_ms = start_seconds * 1000
    end_ms = end_seconds * 1000 if end_seconds is not None else float('inf')
    data['perf'] = [sample for sample in data['perf'] if start_ms <= sample.timestamp_ms <= end_ms]
    for key in ('profiles', 'audio_timing', 'traffic'):
        data[key] = [sample for sample in data[key] if start_ms <= sample['timestamp_ms'] <= end_ms]
    data['metrics_interval'] = (start_seconds, end_seconds)


def print_summary(path: Path, data: dict[str, object]) -> None:
    perf: list[PerfSample] = data["perf"]  # type: ignore[assignment]
    slow_framebuffers: list[tuple[float, str]] = data["slow_framebuffers"]  # type: ignore[assignment]
    pipeline_times: list[int] = data["pipeline_times"]  # type: ignore[assignment]
    memory: list[dict[str, int]] = data["memory"]  # type: ignore[assignment]

    print(f"Log: {path}")
    if 'metrics_interval' in data:
        start, end = data['metrics_interval']
        print(f"Metric report timestamps: {start:g}s to {end if end is not None else 'end'}; faults and other diagnostics cover the whole log")
    print(f"Duration: {data['duration_ms'] / 1000:.1f} s")
    for mode in data["modes"]:  # type: ignore[union-attr]
        print(f"Mode: {mode}")
    if data["pipeline_cache_state"] is not None:
        print(f"Pipeline cache: {data['pipeline_cache_state']}")
    if data["pipeline_cache_saved"] is not None:
        print(f"Pipeline cache: {data['pipeline_cache_saved']}")
    for swapchain in data["swapchains"]:  # type: ignore[union-attr]
        print(f"Output: {swapchain}")
    for ucode in data["ucodes"]:  # type: ignore[union-attr]
        print(f"Microcode: {ucode}")

    audio_first: dict[str, int] | None = data["audio_first"]  # type: ignore[assignment]
    audio_health: list[dict[str, int]] = data["audio_health"]  # type: ignore[assignment]
    if audio_first is None:
        print("Audio: no game samples queued")
    else:
        peak = f" peak={audio_first['peak']}" if "peak" in audio_first else ""
        print(
            "Audio first queue: "
            f"result={audio_first['result']} status={audio_first['status']} "
            f"queued={audio_first['queued']} bytes{peak}"
        )
    if audio_health:
        latest_audio = audio_health[-1]
        print(
            "Audio health: "
            f"queues={latest_audio['queues']} empty-before={latest_audio['empty']} "
            f"failures={latest_audio['failures']} queued={latest_audio['queued']} bytes "
            f"status={latest_audio['status']} peak={latest_audio['peak']}"
        )

    if data["audio_timing"]:
        timing = data["audio_timing"]
        print(f"Audio timing: queue min={min(s['min_us'] for s in timing)/1000:.2f} ms "
              f"max={max(s['max_us'] for s in timing)/1000:.2f} ms; "
              f"production gap max={max(s['gap_us'] for s in timing)/1000:.2f} ms; "
              f"corrected chunks={sum(s['corrections'] for s in timing)}")
    for stage in sorted({sample['stage'] for sample in data['profiles']}):
        windows = [sample for sample in data['profiles'] if sample['stage'] == stage]
        count = sum(s['count'] for s in windows)
        mean = sum(s['mean_us'] * s['count'] for s in windows) / count
        peak = max(windows, key=lambda s: s['max_us'])
        peak_context = (f" peak≈t={peak['max_end_ms']/1000:.3f}s id={peak['max_id']}"
                        if 'max_end_ms' in peak and 'max_id' in peak else "")
        print(f"Profile {stage}: samples={count} mean={mean/1000:.2f} ms "
              f"worst-window p95={max(s['p95_us'] for s in windows)/1000:.2f} ms "
              f"p99={max(s['p99_us'] for s in windows)/1000:.2f} ms "
              f"max={max(s['max_us'] for s in windows)/1000:.2f} ms "
              f"late={sum(s['late'] for s in windows)}{peak_context}")
    for stage in sorted({sample['stage'] for sample in data['traffic']}):
        windows = [sample for sample in data['traffic'] if sample['stage'] == stage]
        byte_count = sum(s['bytes'] for s in windows)
        seconds = sum(s['interval_ns'] for s in windows) / 1e9
        count = sum(s['count'] for s in windows)
        print(f"Traffic {stage}: transfers={count} bytes={byte_count} "
              f"mean={byte_count/count:.0f} bytes/transfer rate={byte_count/seconds/1048576:.2f} MiB/s")
    # Nonblocking logs may drop a line. Compare paired snapshots only, so
    # missing counters cannot manufacture a saving or a negative percentage.
    active = [s for s in data['traffic'] if s['stage'] == 'texture_gpu_staging']
    staged = capacity = matched = 0
    for retained in (s for s in data['traffic'] if s['stage'] == 'texture_staging_capacity'):
        candidates = [s for s in active if s['interval_ns'] == retained['interval_ns']
                      and s['count'] == retained['count']
                      and abs(s['timestamp_ms'] - retained['timestamp_ms']) <= 250]
        if not candidates:
            continue
        sample = min(candidates, key=lambda s: abs(s['timestamp_ms'] - retained['timestamp_ms']))
        active.remove(sample)
        if sample['bytes'] > retained['bytes']:
            continue
        staged += sample['bytes']; capacity += retained['bytes']; matched += 1
    if capacity:
        print(f"Texture staging avoided: {capacity-staged} bytes ({100*(capacity-staged)/capacity:.1f}% of retained capacity); "
              f"matched windows={matched}; logical copy payload, excludes GPU read/write multiplicity")
    if data['batch_status'] is not None:
        passes = sum(bool(re.search(r'\bPASS\b', s)) for s in data['batch_results'])
        print(f"Batched transfers: {passes} passed, {len(data['batch_results'])-passes} failed; suite {data['batch_status']}")

    if perf:
        fps_values = [sample.fps for sample in perf]
        frame_values = [sample.frame_ms for sample in perf]
        gpu_values = [sample.gpu_wait_ms for sample in perf]
        worst = min(perf, key=lambda sample: sample.fps)
        print(
            "Performance: "
            f"{len(perf)} windows, FPS median={statistics.median(fps_values):.2f} "
            f"p10={percentile(fps_values, 0.10):.2f} min={min(fps_values):.2f} "
            f"max={max(fps_values):.2f}"
        )
        print(
            "Frame/GPU: "
            f"frame median={statistics.median(frame_values):.2f} ms "
            f"p95={percentile(frame_values, 0.95):.2f} ms; "
            f"GPU-wait median={statistics.median(gpu_values):.2f} ms "
            f"p95={percentile(gpu_values, 0.95):.2f} ms"
        )
        print(
            f"Worst window: t={worst.timestamp_ms / 1000:.1f}s, "
            f"{worst.fps:.2f} FPS, frame={worst.frame_ms:.2f} ms, "
            f"GPU-wait={worst.gpu_wait_ms:.2f} ms"
        )
        game_start_ms: int | None = data["game_start_ms"]  # type: ignore[assignment]
        gameplay_perf = (
            [sample for sample in perf if sample.timestamp_ms >= game_start_ms]
            if game_start_ms is not None
            else []
        )
        if gameplay_perf:
            gameplay_fps = [sample.fps for sample in gameplay_perf]
            gameplay_gpu = [sample.gpu_wait_ms for sample in gameplay_perf]
            print(
                "Gameplay: "
                f"{len(gameplay_perf)} windows, FPS median={statistics.median(gameplay_fps):.2f} "
                f"p10={percentile(gameplay_fps, 0.10):.2f} min={min(gameplay_fps):.2f}; "
                f"GPU-wait p95={percentile(gameplay_gpu, 0.95):.2f} ms"
            )
    else:
        print("Performance: no samples")

    if pipeline_times:
        print(
            "Pipeline initialization: "
            f"count={len(pipeline_times)}, total={sum(pipeline_times) / 1000:.2f}s, "
            f"median={statistics.median(pipeline_times):.0f} ms, "
            f"p95={percentile([float(value) for value in pipeline_times], 0.95):.0f} ms, "
            f"max={max(pipeline_times)} ms"
        )
    else:
        print("Pipeline initialization: no samples")

    if slow_framebuffers:
        worst_wait, worst_context = max(slow_framebuffers, key=lambda item: item[0])
        print(f"Slow framebuffer submits: count={len(slow_framebuffers)}, max={worst_wait:.2f} ms")
        print(f"Worst framebuffer: {worst_context}")

    if memory:
        peak = max(memory, key=lambda sample: sample["usage"])
        print(
            f"Device memory: peak={peak['usage']} MiB / {peak['budget']} MiB, "
            f"allocation peak={max(sample['allocations'] for sample in memory)} MiB"
        )

    grouped_unknown: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    other_warnings: list[str] = []
    for warning in data["warnings"]:  # type: ignore[union-attr]
        unknown_match = UNKNOWN_GBI_RE.fullmatch(warning)
        if unknown_match is None:
            other_warnings.append(warning)
            continue

        detail_match = re.search(
            r"cmd=(0x[0-9A-Fa-f]+) w0=(0x[0-9A-Fa-f]+) w1=(0x[0-9A-Fa-f]+)",
            unknown_match.group("detail"),
        )
        w0 = detail_match.group(2) if detail_match is not None else ""
        w1 = detail_match.group(3) if detail_match is not None else ""
        key = (
            unknown_match.group("type"),
            unknown_match.group("opcode"),
            unknown_match.group("dl"),
            w0,
            w1,
        )
        group = grouped_unknown.setdefault(key, {"lines": 0, "latest": warning})
        group["lines"] = int(group["lines"]) + 1
        group["latest"] = warning

    extended_command_names = {
        7: "RT64 viewport-align while extended GBI was disabled",
        8: "RT64 scissor-align while extended GBI was disabled",
    }
    for (ucode_type, opcode, dl, w0, _w1), group in grouped_unknown.items():
        latest = str(group["latest"])
        detail_match = re.search(r" (cmd=0x[0-9A-Fa-f]+ w0=0x[0-9A-Fa-f]+ w1=0x[0-9A-Fa-f]+)", latest)
        detail = f" {detail_match.group(1)}" if detail_match is not None else ""
        occurrence_match = re.search(r" occurrences=(\d+)", latest)
        occurrences = occurrence_match.group(1) if occurrence_match is not None else str(group["lines"])
        annotation = ""
        if opcode.lower() == "0x64" and w0:
            command_id = int(w0, 16) & 0xFFFFFF
            if command_id in extended_command_names:
                annotation = f" ({extended_command_names[command_id]})"
        print(
            "Warning: unknown GBI opcode "
            f"type={ucode_type} opcode={opcode} dl={dl}{detail} occurrences={occurrences}{annotation}"
        )
    for warning in other_warnings:
        print(f"Warning: {warning}")
    transfer_results = data["transfer_results"]
    if data["transfer_status"] is not None:
        failures = [result for result in transfer_results if re.search(r"\b(?:FAIL|FAILED)\b", result)]
        passes = [result for result in transfer_results if re.search(r"\bPASS\b", result)]
        print(f"Texture transfers: {len(passes)} passed, {len(failures)} failed; suite {data['transfer_status']}")
        for failure in failures:
            print(f"Transfer failure: {failure}")
    for fault in data["driver_faults"]:
        print(f"Driver: {fault}")
    if data["sampling_status"] is not None:
        failures = [result for result in data["sampling_results"] if re.search(r"\b(?:FAIL|FAILED)\b", result)]
        passes = [result for result in data["sampling_results"] if re.search(r"\bPASS\b", result)]
        print(f"Texture sampling: {len(passes)} passed, {len(failures)} failed; suite {data['sampling_status']}")
        for failure in failures:
            print(f"Sampling failure: {failure}")
    for fatal in data["fatals"]:  # type: ignore[union-attr]
        print(f"Fatal: {fatal}")


def write_csv(path: Path, samples: list[PerfSample]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(PerfSample.__annotations__))
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample.__dict__)


def write_profiles_csv(path: Path, samples: list[dict[str, object]]) -> None:
    fields = ['timestamp_ms', 'stage', 'count', 'mean_us', 'p50_us', 'p95_us', 'p99_us',
              'max_us', 'late', 'id', 'max_id', 'max_age_us', 'max_end_ms', 'interval_ns']
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="nxlink log produced by scripts/switch-run.sh")
    parser.add_argument("--csv", type=Path, help="write parsed performance windows as CSV")
    parser.add_argument("--profiles-csv", type=Path, help="write stage windows and approximate peak times as CSV")
    parser.add_argument("--start-seconds", type=float, help="include sampled metrics reported at/after this log time")
    parser.add_argument("--end-seconds", type=float, help="include sampled metrics reported at/before this log time")
    args = parser.parse_args()

    data = parse_log(args.log)
    if args.start_seconds is not None or args.end_seconds is not None:
        try:
            select_metrics(data, args.start_seconds or 0, args.end_seconds)
        except ValueError as error:
            parser.error(str(error))
    print_summary(args.log, data)
    if args.csv is not None:
        write_csv(args.csv, data["perf"])  # type: ignore[arg-type]
        print(f"CSV: {args.csv}")
    if args.profiles_csv is not None:
        write_profiles_csv(args.profiles_csv, data['profiles'])
        print(f"Profile CSV: {args.profiles_csv}")


if __name__ == "__main__":
    main()
