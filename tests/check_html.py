"""Site HTML validator: tag balance, local links, required notices. Runs in CI."""
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES = ("index.html", "desk.html", "office.html", "changelog.html")


class Collector(HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.unbalanced = [], []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)
        for k, v in attrs:
            if k in ("href", "src") and v and not v.startswith(("http", "#", "data:")):
                self.links.append(v)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.unbalanced.append(tag)
        else:
            self.stack.pop()


def main():
    errors = []
    for page in sorted(SITE.glob("*.html")):
        parser = Collector()
        parser.feed(page.read_text(encoding="utf-8"))
        if parser.unbalanced or parser.stack:
            errors.append(f"{page.name}: unbalanced tags {parser.unbalanced or parser.stack}")
        for link in parser.links:
            target = link.split("?")[0].split("#")[0]
            if target.startswith("data/"):
                continue  # build output, created at deploy time
            if not (SITE / target).exists():
                errors.append(f"{page.name}: broken link {link}")
    # Article 1 is the reason this file exists at all. The repository is called
    # agent-capital, the pages are full of dollar figures and a leaderboard, and a
    # visitor who lands on one of them from a search result has three seconds to
    # work out that none of it is real. Each of these strings is load-bearing, and
    # no agent can quietly drop one without CI going red.
    for page in PAGES:
        text = (SITE / page).read_text(encoding="utf-8")
        if "produced autonomously by AI" not in text:
            errors.append(f"{page}: AI disclaimer footer missing (constitution art. 1)")
        if "No money is invested" not in text:
            errors.append(f"{page}: the 'no money' sentence is missing (constitution art. 1)")
        if "not advice" not in text and "not investment advice" not in text:
            errors.append(f"{page}: the 'not advice' sentence is missing (constitution art. 1)")
        if 'class="badge fiction"' not in text:
            errors.append(f"{page}: the simulation badge is missing from the header "
                          "(constitution art. 1 — above the fold, on every page)")
    for e in errors:
        print("ERROR:", e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
