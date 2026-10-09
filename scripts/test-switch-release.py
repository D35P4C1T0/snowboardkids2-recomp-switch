#!/usr/bin/env python3
"""Exercise release orchestration with mocked builds and GitHub; never publish."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="sk2-release-test-") as directory:
    root = Path(directory)
    (root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/release-switch.sh", root / "scripts/release-switch.sh")
    tools = root / "tools"
    tools.mkdir()

    def executable(path, text):
        path.write_text(text)
        path.chmod(0o755)

    executable(tools / "git", '''#!/usr/bin/env python3
import os,sys
args=sys.argv[1:]
sha='a'*40
if args[0]=='rev-parse': print(sha)
elif args[0]=='status': print(' M source.c' if os.environ.get('DIRTY') else '',end='')
elif args[0]=='remote': print('https://github.com/example/switch-port.git')
elif args[0]=='symbolic-ref': print('codex/test')
elif args[0]=='ls-remote' and args[2].startswith('refs/heads/'):
    print(('b'*40 if os.environ.get('UNPUSHED') else sha)+'\\t'+args[2])
elif args[0]=='ls-remote' and os.environ.get('WRONG_TAG'):
    print('b'*40+'\\t'+args[2])
''')
    executable(tools / "gh", '''#!/usr/bin/env python3
import json,sys,pathlib
if sys.argv[1:3]==['release','create']:
    args=sys.argv[1:]
    pathlib.Path('upload.json').write_text(json.dumps(args))
    notes=pathlib.Path(args[args.index('--notes-file')+1]).read_text()
    pathlib.Path('uploaded-notes.txt').write_text(notes)
''')
    for name in ("cmake", "docker"):
        executable(tools / name, "#!/bin/sh\nexit 0\n")
    executable(root / "scripts/switch-build.sh", '''#!/usr/bin/env python3
from pathlib import Path
import os,zipfile,struct
root=Path.cwd()
build=root/'build-switch-full'
build.mkdir(exist_ok=True)
nro=bytearray(0x80+0x38+0x4000)
nro[0x10:0x14]=b'NRO0'
struct.pack_into('<I',nro,0x18,0x80)
nro[0x80:0x84]=b'ASET'
struct.pack_into('<QQ',nro,0x80+24,0x38,0x4000)
version=b'1.0.0-switch.1'
nro[0x80+0x38+0x3060:0x80+0x38+0x3060+len(version)]=version
(build/'snowboardkids2-recompiled.nro').write_bytes(nro)
count=build/'build-count'
count.write_text(str(int(count.read_text())+1 if count.exists() else 1))
prefix='switch/snowboardkids2-recompiled/'
with zipfile.ZipFile(build/'snowboardkids2-switch.zip','w') as archive:
    archive.write(build/'snowboardkids2-recompiled.nro',prefix+'snowboardkids2-recompiled.nro')
    archive.write('recompcontrollerdb.txt',prefix+'recompcontrollerdb.txt')
    for path in Path('assets').rglob('*'):
        if path.is_file(): archive.write(path,prefix+path.as_posix())
    for marker in ('packed-framebuffer-copyback','fused-framebuffer-transfers'):
        archive.writestr(prefix+'config/'+marker,b'')
    if os.environ.get('CONTAMINATED'): archive.writestr(prefix+'snowboardkids2.z64',b'private ROM')
''')
    (root / "assets").mkdir()
    (root / "assets/font.ttf").write_bytes(b"font")
    (root / "recompcontrollerdb.txt").write_bytes(b"controllers")
    nvk = root / "nvk/lib"
    nvk.mkdir(parents=True)
    (nvk / "libvulkan.a").write_bytes(b"driver")
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
           "SK2_SWITCH_NVK_ROOT": str(root / "nvk")}

    def run(options=(), flags=None, success=True):
        (root / "upload.json").unlink(missing_ok=True)
        result = subprocess.run(["/bin/bash", str(root / "scripts/release-switch.sh"),
                                 "v1.0.0-switch.1", *options], cwd=root,
                                env={**env, **(flags or {})}, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stderr
        return root / "upload.json"

    upload = run(("--build-only",))
    assert not upload.exists()
    upload = run()
    args = json.loads(upload.read_text())
    assert args[:3] == ["release", "create", "v1.0.0-switch.1"]
    assert args[3].endswith("/snowboardkids2-switch.zip")
    assert args[args.index("--repo") + 1] == "example/switch-port"
    assert args[args.index("--target") + 1] == "a" * 40
    assert "no ROM" in (root / "uploaded-notes.txt").read_text()
    custom = root / "custom-notes.md"
    custom.write_text("Custom release notes")
    args = json.loads(run(("--draft", "--prerelease", "--notes-file", str(custom))).read_text())
    assert "--draft" in args and "--prerelease" in args
    assert (root / "uploaded-notes.txt").read_text() == custom.read_text()
    for flag in ("DIRTY", "UNPUSHED", "WRONG_TAG", "CONTAMINATED"):
        assert not run(flags={flag: "1"}, success=False).exists(), flag
    run(("--build-only",))
    count = (root / "build-switch-full/build-count").read_text()
    before = (root / "build-switch-full/snowboardkids2-switch.zip").read_bytes()
    assert run(("--use-existing",)).exists()
    assert count == (root / "build-switch-full/build-count").read_text()
    assert before == (root / "build-switch-full/snowboardkids2-switch.zip").read_bytes()
    nro = root / "build-switch-full/snowboardkids2-recompiled.nro"
    data = bytearray(nro.read_bytes())
    data[0x80+0x38+0x3060] = ord('2')
    nro.write_bytes(data)
    package = root / "build-switch-full/snowboardkids2-switch.zip"
    import zipfile
    with zipfile.ZipFile(package) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents['switch/snowboardkids2-recompiled/snowboardkids2-recompiled.nro'] = bytes(data)
    with zipfile.ZipFile(package, 'w') as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    assert not run(("--use-existing",), success=False).exists()
print("PASS: ZIP-only upload, exact source target, notes/draft/prerelease, local-only mode, source/tag checks and ROM rejection")
