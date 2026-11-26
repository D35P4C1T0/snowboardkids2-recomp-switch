#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

usage() {
    cat <<'HELP'
Usage: scripts/release-switch.sh TAG [--use-existing] [--draft] [--prerelease] [--notes-file FILE] [--build-only]

Build the Switch ZIP locally and create a GitHub release on origin.
TAG must be a version such as v1.0.0-switch.1. Only the ZIP is uploaded.
--use-existing Upload the existing tested ZIP without rebuilding or repackaging.
--draft        Create a draft instead of publishing immediately.
--prerelease   Mark the release as a prerelease.
--notes-file   Use your own Markdown release notes.
--build-only   Build and verify the ZIP without contacting GitHub.
HELP
}

if [[ $# == 0 || ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    exit 0
fi
tag=$1
shift
version=${tag#v}
if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]]; then
    echo "Expected a version tag, for example v1.0.0-switch.1." >&2
    exit 1
fi
build_only=0
use_existing=0
notes_file=
draft=0
prerelease=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --draft) draft=1; shift ;;
        --prerelease) prerelease=1; shift ;;
        --build-only) build_only=1; shift ;;
        --use-existing) use_existing=1; shift ;;
        --notes-file)
            [[ $# -ge 2 && -f $2 ]] || { echo "--notes-file needs an existing file." >&2; exit 1; }
            notes_file=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$2")
            shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

for tool in git python3; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
target_sha=$(git rev-parse HEAD)
git check-ref-format "refs/tags/$tag"
if [[ $build_only == 0 ]]; then
    command -v gh >/dev/null || { echo "Install GitHub CLI and run gh auth login first." >&2; exit 1; }
    gh auth status --hostname github.com >/dev/null
    if [[ -n $(git status --porcelain --untracked-files=normal --ignore-submodules=none) ]]; then
        echo "Commit your source changes before creating a release (or use --build-only)." >&2
        exit 1
    fi
    origin=$(git remote get-url origin)
    case "$origin" in
        https://github.com/*) repository=${origin#https://github.com/} ;;
        git@github.com:*) repository=${origin#git@github.com:} ;;
        *) echo "origin must point to a GitHub repository." >&2; exit 1 ;;
    esac
    repository=${repository%.git}
    [[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "Invalid GitHub origin." >&2; exit 1; }
    branch=$(git symbolic-ref --quiet --short HEAD) || { echo "Check out the branch you want to release." >&2; exit 1; }
    remote_sha=$(git ls-remote origin "refs/heads/$branch" | awk '{print $1}')
    [[ $remote_sha == "$target_sha" ]] || { echo "Push this branch to origin before releasing." >&2; exit 1; }
    # An existing tag may be reused only when it identifies this exact source.
    remote_tag=$(git ls-remote origin "refs/tags/$tag" "refs/tags/$tag^{}")
    if [[ -n $remote_tag ]]; then
        tag_sha=$(printf '%s\n' "$remote_tag" | awk '/\^\{\}$/ { peeled=$1 } { direct=$1 } END { print peeled ? peeled : direct }')
        [[ $tag_sha == "$target_sha" ]] || { echo "Release tag already points at different source; choose a new version." >&2; exit 1; }
    fi
fi

if [[ $use_existing == 0 ]]; then
    for tool in cmake docker; do
        command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
    done
    export GAME_VERSION="$version"
    export DEVKITPRO=${DEVKITPRO:-/opt/devkitpro}
    export SK2_SWITCH_NVK_ROOT=${SK2_SWITCH_NVK_ROOT:-"$REPO_ROOT/build/switch/nvk/source/nvk-switch"}
    if [[ ! -f $SK2_SWITCH_NVK_ROOT/lib/libvulkan.a ]]; then
        "$SCRIPT_DIR/build-switch-nvk.sh"
        [[ -f $SK2_SWITCH_NVK_ROOT/lib/libvulkan.a ]] || { echo "Set SK2_SWITCH_NVK_ROOT to the generated NVK package." >&2; exit 1; }
    fi
    "$SCRIPT_DIR/switch-build.sh" full
fi

archive="$REPO_ROOT/build/switch/full/snowboardkids2-switch.zip"
verify_args=(--verify "$version")
if [[ $build_only == 0 || $use_existing == 1 ]]; then
    verify_args+=(--commit "$target_sha")
fi
if [[ $build_only == 0 ]]; then
    upload_dir=$(mktemp -d)
    trap 'rm -rf -- "$upload_dir"' EXIT
    cp "$archive" "$upload_dir/"
    archive="$upload_dir/${archive##*/}"
fi
python3 "$SCRIPT_DIR/package-switch.py" "${verify_args[@]}" --archive "$archive"

if [[ $build_only == 1 ]]; then
    printf 'Package ready: %s\n' "$archive"
    exit 0
fi
if [[ $(git rev-parse HEAD) != "$target_sha" || -n $(git status --porcelain --untracked-files=normal --ignore-submodules=none) ]]; then
    echo "Source changed during the build; commit, push, and rerun." >&2
    exit 1
fi
if [[ -z $notes_file ]]; then
    notes_file="$REPO_ROOT/build/switch/full/switch-release-notes.md"
    cat > "$notes_file" <<'NOTES'
Native Nintendo Switch homebrew port of Snowboard Kids 2: Recompiled.

1. Extract `snowboardkids2-switch.zip` at the SD-card root, merging `switch/`.
2. Add your own supported ROM as `switch/snowboardkids2-recompiled/snowboardkids2.z64`.
3. Hold R while launching an installed game to open hbmenu through title takeover.
4. Launch the port, choose Load ROM if prompted, then Start Game.

The package contains no ROM. Supported big-endian ROM SHA-1:
`5ce896fd64276948bc2b8cccd8cd51c25a9f32aa`.

Press Select/minus for settings. Modest overclocking can help target stable 60 FPS.
First shader loading can take longer; subsequent launches reuse the SD cache.
NOTES
    printf '\n[Setup guide](https://github.com/%s/blob/%s/README.md) · [Port diary](https://github.com/%s/blob/%s/docs/SWITCH_PORT_DIARY.md)\n' \
        "$repository" "$tag" "$repository" "$tag" >> "$notes_file"
fi
release_args=(release create "$tag" "$archive" \
    --repo "$repository" --target "$target_sha" \
    --title "Snowboard Kids 2 for Switch $tag" \
    --notes-file "$notes_file")
if [[ $draft == 1 ]]; then release_args+=(--draft); fi
if [[ $prerelease == 1 ]]; then release_args+=(--prerelease); fi
gh "${release_args[@]}"
