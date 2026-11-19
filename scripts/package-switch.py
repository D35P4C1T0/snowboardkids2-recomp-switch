#!/usr/bin/env python3
"""Stage and verify the tracked Switch release payload."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build/switch/full"
APP = Path("switch/snowboardkids2-recompiled")
NRO = "snowboardkids2-recompiled.nro"
ARCHIVE = BUILD / "snowboardkids2-switch.zip"
PROVENANCE = BUILD / "snowboardkids2-switch.provenance.json"
ROM_MAGIC = {bytes.fromhex(magic) for magic in ("80371240", "37804012", "40123780")}
ASSET_SUFFIXES = {".png", ".rcss", ".svg", ".ttf", ".txt"}


def payload(packed_only=False):
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "assets/", "recompcontrollerdb.txt"], cwd=ROOT
    )
    paths = [Path(os.fsdecode(name)) for name in tracked.split(b"\0") if name]
    if Path("recompcontrollerdb.txt") not in paths or len(paths) < 2:
        raise ValueError("Missing tracked Switch assets or controller database")

    files = {APP / NRO: (BUILD / NRO).read_bytes()}
    for path in paths:
        source = ROOT / path
        if source.resolve() != source or not source.is_file():
            raise ValueError(f"Expected a regular tracked package file: {path}")
        data = source.read_bytes()
        if path.suffix.lower() not in ASSET_SUFFIXES or data[:4] in ROM_MAGIC:
            raise ValueError(f"Unexpected file type in tracked package inputs: {path}")
        files[APP / path] = data
    files[APP / "config/packed-framebuffer-copyback"] = b""
    if not packed_only:
        files[APP / "config/fused-framebuffer-transfers"] = b""
    return files


def pack(packed_only):
    files = payload(packed_only)
    stage = BUILD / ("sdcard-packed" if packed_only else "sdcard")
    archive = BUILD / "snowboardkids2-switch-packed-copyback.zip" if packed_only else ARCHIVE
    with tempfile.TemporaryDirectory(prefix="package-", dir=BUILD) as directory:
        work = Path(directory)
        new_stage = work / "stage"
        with zipfile.ZipFile(work / archive.name, "w", zipfile.ZIP_DEFLATED) as package:
            for path, data in files.items():
                target = new_stage / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                entry = zipfile.ZipInfo(path.as_posix())
                entry.external_attr = 0o100644 << 16
                package.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)

        previous = work / "previous"
        if stage.exists() or stage.is_symlink():
            if stage.is_symlink() or not stage.is_dir() or any(
                path.is_symlink() or (not path.is_dir() and path.relative_to(stage) not in files)
                for path in stage.rglob("*")
            ):
                previous = Path(tempfile.mkdtemp(prefix=f"{stage.name}-previous-", dir=BUILD)) / stage.name
            stage.rename(previous)
        try:
            new_stage.rename(stage)
        except OSError:
            if previous.exists() or previous.is_symlink():
                previous.rename(stage)
            raise
        if previous.parent != work:
            print(f"Preserved previous staging files in {previous}")
        (work / archive.name).replace(archive)

    print(f"Switch SD-card package: {stage / APP}")
    print(f"Switch SD-card archive: {archive}")
    print("Copy your own supported ROM to the SD card as snowboardkids2.z64.")


def digest(archive):
    with archive.open("rb") as stream:
        sha = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
        return sha.hexdigest()


def record(commit):
    with tempfile.NamedTemporaryFile(mode="w", dir=BUILD, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            json.dump({"commit": commit, "sha256": digest(ARCHIVE)}, temporary)
            temporary.close()
            path.replace(PROVENANCE)
        finally:
            path.unlink(missing_ok=True)


def verify(archive, version, commit):
    if commit:
        if not PROVENANCE.is_file():
            raise ValueError("Build provenance is missing. Rebuild the Switch ZIP for this commit.")
        provenance = json.loads(PROVENANCE.read_text())
        if provenance != {"commit": commit, "sha256": digest(archive)}:
            raise ValueError("Build provenance does not match this source commit and ZIP.")

    files = payload()
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(files) or set(names) != {path.as_posix() for path in files}:
            raise ValueError("ZIP has missing, duplicate or unexpected files.")
        if any(stat.S_ISLNK(entry.external_attr >> 16) for entry in package.infolist()):
            raise ValueError("ZIP contains a symbolic link.")
        if any(package.read(path.as_posix()) != data for path, data in files.items()):
            raise ValueError("ZIP does not match the current NRO, assets or optimization settings.")

    nro = files[APP / NRO]
    if nro[0x10:0x14] != b"NRO0":
        raise ValueError("Invalid NRO header")
    asset = struct.unpack_from("<I", nro, 0x18)[0]
    if nro[asset:asset + 4] != b"ASET":
        raise ValueError("Missing NRO assets")
    nacp, size = struct.unpack_from("<QQ", nro, asset + 24)
    if size < 0x3070 or asset + nacp + size > len(nro):
        raise ValueError("Invalid NACP bounds")
    actual = nro[asset + nacp + 0x3060:asset + nacp + 0x3070].split(b"\0")[0].decode()
    if actual != version:
        raise ValueError(f"Packaged version is {actual}; use the matching release tag or rebuild.")
    print("Verified release ZIP and tracked package contents.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--packed-copyback", action="store_true")
    mode.add_argument("--fused-transfers", action="store_true")
    mode.add_argument("--record", metavar="COMMIT")
    mode.add_argument("--verify", metavar="VERSION")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--commit")
    args = parser.parse_args()
    try:
        if args.record:
            record(args.record)
        elif args.verify:
            verify(args.archive, args.verify, args.commit)
        else:
            pack(args.packed_copyback)
    except (OSError, ValueError, struct.error, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
