"""
The packaging step must refuse to build a package that would be rejected.

A fresh clone cannot simply be zipped: the icons are generated rather than committed, so the manifest
would name four files that are not there and Chrome would refuse to load the package at all. These tests
check that the build catches that, and the other ways a package goes wrong, instead of producing a zip
that fails in someone else's hands.
"""
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from aura.tools import package_extension as pkg

pytest.importorskip("PIL.Image")  # the icons are generated with Pillow


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """A copy of the real extension, so a test can break it without breaking the repository."""
    ext = tmp_path / "extension"
    shutil.copytree(pkg.EXT, ext)
    monkeypatch.setattr(pkg, "EXT", ext)
    monkeypatch.setattr(pkg, "ROOT", tmp_path)
    monkeypatch.setattr(pkg, "DIST", tmp_path / "dist")
    return ext


def test_the_real_extension_passes_every_check():
    pkg.check(verbose=False)


def test_a_missing_icon_stops_the_build(staged):
    (staged / "icons" / "icon16.png").unlink()
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "icon16.png" in str(e.value)
    # And it says how to fix it, because this is what a fresh clone always hits.
    assert "sync_extension_assets" in str(e.value)


def test_a_new_file_in_a_known_folder_is_packaged_without_being_asked(staged):
    """A module added beside the others ships: the include list is by folder, not by name."""
    (staged / "sidepanel" / "new_module.js").write_text("export const x = 1;", encoding="utf-8")
    files = pkg.check(verbose=False)
    assert any(f.name == "new_module.js" for f in files)


def test_a_file_in_a_folder_nobody_listed_stops_the_build(staged):
    """A new FOLDER is the real risk: it would be dropped silently and the extension would break."""
    (staged / "workers").mkdir()
    (staged / "workers" / "worker.js").write_text("self.onmessage = () => {};", encoding="utf-8")
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "workers/worker.js" in str(e.value)


def test_a_remote_script_stops_the_build(staged):
    page = staged / "sidepanel" / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "</head>", '<script src="https://cdn.example.com/x.js"></script></head>'), encoding="utf-8")
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "remote script" in str(e.value)


def test_something_shaped_like_a_key_stops_the_build(staged):
    target = staged / "sidepanel" / "api.js"
    target.write_text(target.read_text(encoding="utf-8")
                      + '\nconst oops = "gsk_abcdefghij0123456789";\n', encoding="utf-8")
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "API key" in str(e.value)


def test_a_missing_export_stops_the_build(staged):
    """The failure this catches is a side panel that opens blank."""
    target = staged / "sidepanel" / "api.js"
    text = target.read_text(encoding="utf-8").replace("export async function getAiChoice(",
                                                      "async function getAiChoice(")
    target.write_text(text, encoding="utf-8")
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "getAiChoice" in str(e.value)


def test_a_vendored_file_without_its_licence_stops_the_build(staged):
    (staged / "vendor" / "LICENSE-axe-core-MPL-2.0.txt").unlink()
    with pytest.raises(pkg.Problem) as e:
        pkg.check(verbose=False)
    assert "licence" in str(e.value).lower() and "MPL" in str(e.value)


def test_the_built_package_holds_what_chrome_needs(staged, tmp_path):
    out = pkg.build()
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        # Every path the manifest names resolves inside the zip, which is what Chrome checks on load.
        for ref in pkg._manifest_references(manifest):
            assert ref in names, f"the package does not contain {ref}, which its manifest names"
        assert "vendor/axe.min.js" in names and "vendor/LICENSE-axe-core-MPL-2.0.txt" in names
        assert not [n for n in names if n.endswith((".map", ".log", ".zip"))]
        assert all(zf.read(n) for n in names if n.endswith(".png")), "an icon came out empty"


def test_the_tool_prints_nothing_a_windows_console_cannot_show():
    """
    The build ran, the zip was written, and then the summary line killed the process on cp1252. A tool
    whose output crashes is a tool that looks like it failed.
    """
    source = Path(pkg.__file__).read_text(encoding="utf-8")
    offenders = sorted({c for c in source if ord(c) > 127})
    assert not offenders, f"package_extension.py contains {offenders}, which a cp1252 console cannot print"
