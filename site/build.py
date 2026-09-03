"""Site data packager: copies company/ content into site/data.

Deterministic and offline. It makes no network call and no model call, which is
what lets the same command run in CI, on a laptop, and on every Pages deploy and
produce the same bytes.

It also does one thing that is not copying. The kernel writes a hallway line as
"<colleague>: <what they said>" and the page prints the colleague separately, off
the roster, so a model that signs its own line puts the name on the page twice —
and next door one of them once signed with the name of a colleague who did not
exist. Speaker prefixes come off here, at the point of display. What is in
company/hallway is left exactly as written, because that file is the record and a
record does not get tidied.
"""
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site/data"

sys.path.insert(0, str(ROOT / "assets"))
import avatars  # noqa: E402  (portrait parts; pure computation, no network)

# Two or three capitalised words in front of a colon, never one: "Note:" and
# "Week 35:" are things a colleague may legitimately open with; "Liam Zhou:" is not.
SPEAKER = re.compile(r"^\s*[A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*){1,2}\s*:\s*")


def hallway_line(text):
    """One hallway line with any speaker prefixes stripped off the front."""
    line = " ".join(text.split("\n")[0].split())
    for _ in range(3):
        shorter = SPEAKER.sub("", line, count=1)
        if shorter == line or not shorter:
            break
        line = shorter
    return line


def roster_public(root):
    """Publish the desk as people: kernel schema, identity and wardrobe, merged."""
    rows = json.loads((root / "company/roster.json").read_text(encoding="utf-8"))
    people = {p["id"]: p for p in json.loads(
        (root / "company/agents/identity.json").read_text(encoding="utf-8"))}
    out = []
    for r in rows:
        who = people.get(r["id"], {})
        out.append({"id": r["id"], "name": who.get("person", r["ad"]),
                    "title": who.get("title", r["rol"]), "room": who.get("room", "The floor"),
                    "bio": who.get("bio", ""), "role": r["rol"], "shifts": r["gunler"],
                    "mandate": r.get("mandate", ""),
                    "advisor": bool(r.get("driven_by"))})
    return out


def changelog(root, agent_ids):
    """Only autonomous merges belong on the public changelog."""
    prefixes = tuple(f"{a}: " for a in agent_ids) + ("desk: ", "chief: ", "evaluator: ")
    entries = []
    try:
        out = subprocess.run(["git", "log", "-n", "400", "--pretty=format:%as%x09%s"],
                             cwd=root, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return entries
    for line in out.splitlines():
        date, _, subject = line.partition("\t")
        if subject.startswith(prefixes):
            entries.append({"date": date, "message": subject})
    return entries


def _copy_json_tree(source, target):
    if source.exists():
        shutil.copytree(source, target)


def _latest(folder, suffix=".json"):
    files = sorted(p for p in folder.glob(f"*{suffix}")) if folder.exists() else []
    return files[-1] if files else None


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    data = ROOT / "company/data"
    for name in ("nav", "portfolios", "prices", "orders"):
        _copy_json_tree(data / name, OUT / name)
    for name in ("leaderboard.json", "universe.json", "sources.json", "evolution.json"):
        if (data / name).exists():
            shutil.copy(data / name, OUT / name)

    # The pages want today's two files without having to guess a filename.
    for folder, alias in (("prices", "prices-latest.json"), ("orders", "orders-latest.json")):
        newest = _latest(data / folder)
        if newest:
            shutil.copy(newest, OUT / alias)

    if (ROOT / "company/minutes").exists():
        shutil.copytree(ROOT / "company/minutes", OUT / "minutes")
    if (ROOT / "company/evolution").exists():
        shutil.copytree(ROOT / "company/evolution", OUT / "evolution")
        newest = _latest(ROOT / "company/evolution", ".md")
        if newest:
            shutil.copy(newest, OUT / "evolution-latest.md")
    if (ROOT / "company/hallway").exists():
        (OUT / "hallway").mkdir(parents=True, exist_ok=True)
        for src in sorted((ROOT / "company/hallway").glob("*.txt")):
            (OUT / "hallway" / src.name).write_text(
                hallway_line(src.read_text(encoding="utf-8")) + "\n", encoding="utf-8")

    shutil.copytree(ROOT / "company/agents/prompts", OUT / "prompts")
    shutil.copy(ROOT / "company/constitution.md", OUT / "constitution.md")
    avatars.write_all(OUT / "avatars", ROOT)

    roster = roster_public(ROOT)
    (OUT / "roster.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=1), encoding="utf-8")

    name = ""
    for line in (ROOT / "company/constitution.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("Company name:") and "not chosen" not in line:
            name = line.split(":", 1)[1].strip()
    (OUT / "name.txt").write_text(name, encoding="utf-8")

    (OUT / "changelog.json").write_text(
        json.dumps(changelog(ROOT, [r["id"] for r in roster]), ensure_ascii=False),
        encoding="utf-8")

    files = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file())
    (OUT / "manifest.json").write_text(json.dumps(
        {"generated": dt.datetime.utcnow().isoformat(timespec="seconds"), "files": files},
        ensure_ascii=False), encoding="utf-8")
    print(f"site/data ready: {len(files)} files")


if __name__ == "__main__":
    main()
