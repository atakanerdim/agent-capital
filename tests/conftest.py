import json, os, shutil, stat, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

# Everything the agents pile up as the company runs. A test that reads any of this
# is really reading whatever week the company happens to be in, which is why the
# fixture wipes it: tests describe behaviour, never accumulated history.
ACCUMULATED = ("company/minutes", "company/hallway", "company/log",
               "company/evolution", "company/data/prices", "company/data/orders",
               "company/data/portfolios", "company/data/nav",
               "company/data/income")

# Files the desk writes as it runs, as opposed to directories it fills.
ACCUMULATED_FILES = ("company/data/leaderboard.json", "company/data/evolution.json")

# The chief writes the company's name into the constitution's first line, once
# ever, and never touches it again. That line is accumulated state exactly like a
# NAV series is, and it was the one piece the wipe above missed: left in place, the
# copy carries whichever Sunday the company has already had, and a test that asks
# what the chief does on an unnamed company is instead asking what he does on a
# named one. The line is restored to what it says on opening day.
UNNAMED = ("Company name: not chosen yet — the Chief Investment Officer names "
           "this company on a Sunday.")


def _rmtree(path):
    """Remove a tree, clearing the read-only flag Windows refuses to delete through.

    On Windows os.rmdir refuses a directory carrying FILE_ATTRIBUTE_READONLY with
    "Access is denied", even when it is empty, and shutil.copytree carries that flag
    from the source into every copy the fixture makes. Waiting does not help: the
    attribute never clears on its own. Clearing it does.

    Measured on 2026-08-22: every directory of one working copy was 0x11
    READONLY|DIRECTORY, and the same rmdir succeeded immediately after a chmod.
    Guarded by os.name because S_IWRITE means something else entirely on POSIX —
    setting it there would strip the read and execute bits and break traversal.
    """
    if os.name == "nt":
        for item in (path, *path.rglob("*")):
            try:
                os.chmod(item, stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path)


def _wipe(directory):
    for item in directory.glob("*"):
        if item.name == ".gitkeep":
            continue
        _rmtree(item) if item.is_dir() else item.unlink()


@pytest.fixture
def company(tmp_path, monkeypatch):
    """A pristine working copy of the company, plus the mock environment.

    The desk on disk grows every day: prices, orders, portfolios, a NAV series per
    advisor, minutes, hallway lines and error logs. A test written against that
    state passes on the day it is written and fails a fortnight later for reasons
    that have nothing to do with the code. So the copy starts on its opening day
    with eight empty books.
    """
    for d in ("kernel", "company", "site"):
        shutil.copytree(ROOT / d, tmp_path / d)
    (tmp_path / "out").mkdir()
    # site/data is build output, not source. A working copy that has ever been
    # built carries it, and on Windows it arrives READONLY|DIRECTORY; build.py's
    # own clean-out then dies on "Access is denied" before a single test runs.
    # A pristine copy has never been built.
    if (tmp_path / "site/data").exists():
        _rmtree(tmp_path / "site/data")

    shutil.copytree(ROOT / "assets", tmp_path / "assets")
    shutil.copytree(ROOT / "tests", tmp_path / "tests")

    for rel in ACCUMULATED:
        directory = tmp_path / rel
        directory.mkdir(parents=True, exist_ok=True)
        _wipe(directory)
    for rel in ACCUMULATED_FILES:
        (tmp_path / rel).unlink(missing_ok=True)

    constitution = tmp_path / "company/constitution.md"
    lines = constitution.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("Company name:"):
        lines[0] = UNNAMED
        constitution.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Every advisor starts from the opening allocation with an empty book. A test
    # that inherited yesterday's positions would be measuring the day the test was
    # written, which is the trap this whole fixture exists to avoid — and which
    # this project has already walked into twice on the desk next door.
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setenv("MOCK_HTTP", "1")
    monkeypatch.setenv("MOCK_ANSWERS", str(ROOT / "tests" / "mock_answers.json"))
    return tmp_path


@pytest.fixture
def logic():
    """Load a logic module by path, the way the kernel does."""
    import importlib.util

    def load(root, name):
        path = Path(root) / "company/agents/logic" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"logic_{name}_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load
