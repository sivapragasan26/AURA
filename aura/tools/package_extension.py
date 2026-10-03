"""
Builds the extension package for the Chrome Web Store, and refuses to build a broken one.

A fresh clone cannot be zipped and submitted as it stands: the icons are generated rather than committed
(.gitignore excludes *.png), so the manifest would reference four files that are not there and Chrome
would refuse to load the package at all. Running this instead of zipping the folder by hand means that
kind of thing is caught here rather than by a reviewer three days later.

    python -m aura.tools.package_extension            build dist/aura-extension-<version>.zip
    python -m aura.tools.package_extension --check    run the checks only, write nothing

What it checks: every file the manifest names exists; every file in the package is one the extension
actually uses; no page loads a remote script; no provider key is anywhere in the package; the vendored
axe-core carries its licence; and every name one module imports from another is really exported (a missing
export is a side panel that opens blank, with the reason only in a console a user never opens).
"""
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
DIST = ROOT / "dist"

# Files that belong in a published package, as glob patterns against the extension folder.
INCLUDE = [
    "manifest.json",
    "*.js",            # background.js and the activation module it imports
    "icons/*.png",
    "sidepanel/*.html", "sidepanel/*.css", "sidepanel/*.js",
    "options/*.html", "options/*.css", "options/*.js",
    "content/*.js",
    "vendor/axe.min.js",
    "vendor/LICENSE-axe-core-MPL-2.0.txt",
]
# Never shipped, whatever else matches.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDE_SUFFIXES = {".map", ".log", ".zip", ".bak", ".orig"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
]


class Problem(Exception):
    pass


def _files() -> List[Path]:
    seen = []
    for pattern in INCLUDE:
        for path in sorted(EXT.glob(pattern)):
            if path.is_file() and path.name not in EXCLUDE_NAMES and path.suffix not in EXCLUDE_SUFFIXES:
                seen.append(path)
    return seen


def _manifest() -> dict:
    try:
        return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Problem(f"manifest.json could not be read: {e}")


def _manifest_references(manifest: dict) -> List[str]:
    """Every file path the manifest names, wherever it names it."""
    refs = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str) and re.fullmatch(r"[\w./\-]+\.(png|html|js|css|json|txt)", value):
            refs.append(value)

    walk(manifest)
    return sorted(set(refs))


def check(verbose: bool = True) -> List[Path]:
    """Everything that must hold before a package is worth building. Raises Problem on the first failure."""
    def say(line):
        if verbose:
            print(line)

    manifest = _manifest()
    version = manifest.get("version")
    if not version:
        raise Problem("the manifest has no version")

    # 1. Everything the manifest names is there.
    missing = [ref for ref in _manifest_references(manifest) if not (EXT / ref).is_file()]
    if missing:
        raise Problem(
            f"the manifest names files that do not exist: {missing}. The icons are generated, not "
            f"committed: run `python -m aura.tools.sync_extension_assets` (it needs Pillow).")
    say(f"  every file the manifest names is present ({len(_manifest_references(manifest))} of them)")

    files = _files()
    if not files:
        raise Problem("no files matched the include list; is this the right directory?")

    # 2. Nothing in the extension folder is being left out by accident.
    packaged = {p.relative_to(EXT).as_posix() for p in files}
    on_disk = {
        p.relative_to(EXT).as_posix() for p in EXT.rglob("*")
        if p.is_file() and p.name not in EXCLUDE_NAMES and p.suffix not in EXCLUDE_SUFFIXES
    }
    forgotten = sorted(on_disk - packaged)
    if forgotten:
        raise Problem(f"these files are in extension/ but would not be packaged: {forgotten}. Add them to "
                      f"INCLUDE if they are needed, or delete them.")
    say(f"  nothing in extension/ is left out ({len(packaged)} files)")

    # 3. No remote code, in any page or script.
    for path in files:
        if path.suffix not in (".html", ".js"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "axe.min.js":
            continue
        if re.search(r"<script[^>]+src=[\"']https?://", text):
            raise Problem(f"{path.name} loads a remote script. The store submission declares no remote code.")
        for pattern in SECRET_PATTERNS:
            found = pattern.search(text)
            if found:
                raise Problem(f"{path.name} contains something shaped like an API key "
                              f"({found.group()[:12]}...). It must not be in the package.")
    say("  no remote code and nothing shaped like an API key")

    # 4. Every import resolves. A missing export opens a blank panel.
    exports, problems = {}, []
    for path in files:
        if path.suffix != ".js" or path.name == "axe.min.js":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        exports[path.name] = set(re.findall(r"export\s+(?:async\s+)?(?:function|const|class)\s+([A-Za-z_$][\w$]*)", text))
    for path in files:
        if path.suffix != ".js" or path.name == "axe.min.js":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for imported, module in re.findall(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", text):
            target = Path(module).name
            if target not in exports:
                problems.append(f"{path.name} imports from {module}, which is not in the package")
                continue
            for raw in imported.split(","):
                name = raw.strip().split(" as ")[0].strip()
                if name and name not in exports[target]:
                    problems.append(f"{path.name} imports '{name}' from {target}, which does not export it")
    if problems:
        raise Problem("the modules do not line up: " + "; ".join(problems))
    say("  every import resolves to a real export")

    # 5. The vendored licence travels with the vendored file.
    if (EXT / "vendor" / "axe.min.js").is_file() and not (EXT / "vendor" / "LICENSE-axe-core-MPL-2.0.txt").is_file():
        raise Problem("axe-core is vendored without its licence. The MPL requires the licence to travel "
                      "with the file; see THIRD-PARTY-NOTICES.md.")
    say("  the vendored licence is present")

    return files


def build() -> Path:
    """Generates the assets, runs every check, and writes the zip."""
    print("Preparing the extension package")
    print("- generating assets")
    try:
        from aura.tools.sync_extension_assets import make_icons, sync
        sync()
        make_icons()
    except ImportError as e:
        raise Problem(f"the asset sync is unavailable ({e}); it needs Pillow for the icons")

    print("- checking the package")
    files = check()

    manifest = _manifest()
    version = manifest["version"]
    DIST.mkdir(exist_ok=True)
    out = DIST / f"aura-extension-{version}.zip"
    if out.exists():
        out.unlink()
    # Fixed timestamps so the same source produces the same zip.
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(EXT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

    size_kb = out.stat().st_size / 1024
    print(f"\n{out.relative_to(ROOT)} : {len(files)} files, {size_kb:.0f} KB, version {version}")
    print("Load it with chrome://extensions > Load unpacked (the extension/ folder), or submit the zip.")
    print("Still to produce by hand: listing artwork (see docs/STORE-LISTING.md).")
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if "--check" in argv:
            print("Checking the extension package (writing nothing)")
            check()
            print("\nEverything checks out.")
        else:
            build()
    except Problem as e:
        print(f"\nNot packaged: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
