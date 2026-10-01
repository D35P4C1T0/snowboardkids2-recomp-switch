#!/usr/bin/env python3
"""Check the Switch patches against pinned sources without an SDK or ROM."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / "switch/patches"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, **kwargs)


def snapshot(tree):
    return {
        str(path.relative_to(tree)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tree.rglob("*") if path.is_file()
    }


def main():
    series = [
        line.split() for line in (PATCHES / "series").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    with tempfile.TemporaryDirectory(prefix="build-patch-test-", dir=ROOT) as temp:
        temp = Path(temp)
        original = temp / "original"
        candidate = temp / "candidate"
        for dependency, patch in series:
            # Export only files the patches touch; nested repositories have
            # their own entries in the series and their own pinned HEAD.
            paths = run("git", "apply", "--numstat", str(PATCHES / patch)).stdout.decode()
            source = ROOT / "lib" / dependency
            for entry in paths.splitlines():
                path = entry.split("\t", 2)[2]
                target = original / dependency / path
                target.parent.mkdir(parents=True, exist_ok=True)
                tree_entry = run("git", "-C", str(source), "ls-tree", "HEAD", "--", path).stdout
                if not tree_entry:
                    continue  # File added by the patch.
                target.write_bytes(run("git", "-C", str(source), "show", f"HEAD:{path}").stdout)
                target.chmod(int(tree_entry.split()[0], 8) & 0o777)

        pristine = snapshot(original)
        shutil.copytree(original, candidate)
        apply_script = str(ROOT / "scripts/apply-switch-patches.sh")
        run("sh", apply_script, str(candidate))
        patched = snapshot(candidate)
        assert patched != pristine, "No patches were applied"
        run("sh", apply_script, str(candidate), "--check")
        run("sh", apply_script, str(candidate))
        assert snapshot(candidate) == patched, "Repeated application changed the source"

        for dependency, patch in reversed(series):
            run("git", "apply", "--reverse",
                f"--directory={candidate.relative_to(ROOT)}/{dependency}",
                str(PATCHES / patch))
        assert snapshot(candidate) == pristine, "Reverse application did not restore the source"
        result = subprocess.run(["sh", apply_script, str(candidate), "--check"], cwd=ROOT, capture_output=True)
        assert result.returncode != 0, "Verification accepted unpatched sources"

        # A mismatch in the LAST dependency must be caught before the FIRST
        # dependency is written. This guards against partially patched builds.
        dependency, patch = series[-1]
        touched = run("git", "apply", "--numstat", str(PATCHES / patch)).stdout.decode().splitlines()
        existing = next(candidate / dependency / line.split("\t", 2)[2]
                        for line in touched
                        if (candidate / dependency / line.split("\t", 2)[2]).is_file())
        existing.write_text("Deliberately incompatible dependency for preflight test.\n")
        corrupted = snapshot(candidate)
        result = subprocess.run(["sh", apply_script, str(candidate)], cwd=ROOT, capture_output=True)
        assert result.returncode != 0, "Incompatible source was accepted"
        assert snapshot(candidate) == corrupted, "Preflight failure partially patched the tree"

        result = subprocess.run(["sh", apply_script, str(ROOT / "lib")], cwd=ROOT, capture_output=True)
        assert result.returncode != 0, "Canonical submodules were accepted as a patch destination"

    print(f"PASS: {len(series)} pinned patches, repeat application, reverse round trip, preflight failure, destination guard")


if __name__ == "__main__":
    main()
