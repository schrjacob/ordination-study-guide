"""Build an Anki deck (anki/Ordination Study Guide.apkg) from the Markdown in docs/.

Every page in mkdocs.yml's nav becomes a subdeck, e.g. Ordination::Bible::Old Testament::Pentateuch.
Cards are tagged by exam (bible, theology, ...) and tier (tier1, tier2, tier3), using the same tier
rules as the website's tier filter (docs/assets/javascripts/tiers.js).

What becomes a card:
  - Table rows: the first column is the prompt, the other columns the answer. A "Tier" column sets
    the tier. Passage and event tables also get a reverse card (location -> passage).
  - Book outlines: the main divisions of each book, and each division's contents.
  - Book summaries: the one-line summary from the OT/NT overviews, with the book's title line.
  - "Key chapters"-style lists (items that start with a bold reference) become locate cards both ways.
  - Lists whose items start with a bold term ("**Christ** = ...") become one card per item; other
    lists become one card for the whole list under its heading.

Notes keep a stable ID (deck + prompt), so re-importing after edits updates cards in place and keeps
your review history.

Usage:  python scripts/build_anki.py [--out "anki/Ordination Study Guide.apkg"]
"""

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path

import genanki
import markdown
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_booklet import read_page  # noqa: E402  (shared Markdown block parser)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TIERS_JS = DOCS / "assets" / "javascripts" / "tiers.js"
DEFAULT_OUT = ROOT / "anki" / "Ordination Study Guide.apkg"
ROOT_DECK = "Ordination"

# --------------------------------------------------------------------------
# Tier rules (mirrors tiers.js)
# --------------------------------------------------------------------------

BOOK_PAGES = {  # page <h1> -> tier of non-book sections on the page
    "The Pentateuch": 3, "Historical Books": 3, "Poetry & Wisdom": 3, "Major Prophets": 3,
    "Minor Prophets (The Twelve)": 3, "The Gospels": 2, "Acts": 2, "Pauline Epistles": 3,
    "General Epistles & Revelation": 3,
}
# page <h1> -> (default tier, [(regex on h2/h3, tier)], star tier, rest tier)
REFERENCE_PAGES = {
    "Theology": (3, [(r"^Shorter Catechism", 1), (r"^The Hot Topics", 2)], None, None),
    "Core Doctrines and Proofs": (1, [], None, None),
    "Whole Bible": (1, [], None, None),
    "Old Testament": (1, [(r"^Hebrew Divisions", 3)], None, None),
    "New Testament": (1, [], None, None),
    "OT Timeline & Covenants": (1, [], None, None),
    "OT Key Passages & Events": ("star", [], 1, 3),
    "OT People & Places": (3, [(r"^Key People", "star")], 2, 3),
    "NT People & Places": (3, [(r"^Key People", "star")], 2, 3),
    "NT Key Passages": (1, [], None, None),
    "NT Key Topics": (2, [], None, None),
    "Life of Paul & Missionary Journeys": (2, [(r"^Why the Order Matters", 3)], None, None),
    "Life of Christ": (3, [(r"Parables|Miracles", 2)], None, None),
}
REVERSE_PAGES = {"OT Key Passages & Events", "NT Key Passages"}
BOOK_HEADING = re.compile(r"^(.*?)\s*\((\d+(?: \+ \d+)?)\)\s*$")
BOLD_REF = re.compile(r"^\*\*([0-9](?:[0-9:,\- ]*[0-9])?)\*\*\s+(.*)$")
BOLD_LEAD = re.compile(r"^\*\*([^*]+?)\*\*\s*(?::|=|-|—)?\s*(.+)$")


def js_list(name):
    """Read a book list (TIER1_OUTLINES, TIER2_OUTLINES) from tiers.js."""
    src = TIERS_JS.read_text(encoding="utf-8")
    m = re.search(name + r"\s*=\s*\[(.*?)\]", src, re.S)
    return re.findall(r'"([^"]+)"', m.group(1))


TIER1_OUTLINES = js_list("TIER1_OUTLINES")
TIER2_OUTLINES = js_list("TIER2_OUTLINES")


def outline_tier(book):
    return 1 if book in TIER1_OUTLINES else 2 if book in TIER2_OUTLINES else 3


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def to_html(text):
    """Inline Markdown -> HTML; links become plain text (they would be dead inside Anki)."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r":[a-z][a-z0-9]*(?:-[a-z0-9]+)+:", "", text)
    out = markdown.markdown(text.replace("<br>", "\n\n"))
    out = re.sub(r"^<p>|</p>$", "", out.strip())
    return out.replace("</p>\n<p>", "<br>")


def plain(text):
    return re.sub(r"<[^>]+>", "", html.unescape(to_html(text))).strip()


def list_html(items, base_level=0):
    """[(level, marker, text)] -> nested <ul>."""
    out, depth = [], base_level - 1
    for level, _marker, text in items:
        while depth < level:
            out.append("<ul>")
            depth += 1
        while depth > level:
            out.append("</ul>")
            depth -= 1
        out.append(f"<li>{to_html(text)}</li>")
    while depth >= base_level:
        out.append("</ul>")
        depth -= 1
    return "".join(out)


def stable_id(*parts):
    return int(hashlib.sha1("::".join(parts).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------
# Anki models
# --------------------------------------------------------------------------

CSS = """
.card { font-family: "Source Sans 3", "Segoe UI", Arial, sans-serif; font-size: 19px;
        line-height: 1.45; text-align: left; color: #222; background: #fff; padding: 0 6px; }
.nightMode.card, .night_mode .card { color: #ddd; background: #1e1e1e; }
.ctx { font-size: 13px; color: #888; margin-bottom: 10px; }
.prompt { font-size: 22px; font-weight: 600; }
.answer { margin-top: 4px; }
.answer ul { margin: 4px 0 4px 1.1em; padding: 0; }
.answer li { margin: 2px 0; }
hr#answer { margin: 14px 0; }
b, strong { color: #3f51b5; }
.nightMode b, .nightMode strong, .night_mode b, .night_mode strong { color: #9fa8da; }
.tier { float: right; font-size: 12px; color: #aaa; }
"""

FIELDS = [{"name": "Prompt"}, {"name": "Answer"}, {"name": "Context"}, {"name": "Tier"},
          {"name": "Reverse"}]
FRONT = '<div class="ctx">{{Context}}<span class="tier">{{Tier}}</span></div><div class="prompt">{{Prompt}}</div>'
BACK = '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>'
REV_FRONT = ('{{#Reverse}}<div class="ctx">{{Context}}<span class="tier">{{Tier}}</span></div>'
             '<div class="prompt">{{Reverse}}</div>{{/Reverse}}')
REV_BACK = '{{FrontSide}}<hr id="answer"><div class="answer">{{Prompt}}</div>'

MODEL = genanki.Model(
    1607392319, "Ordination Study Guide",
    fields=FIELDS,
    templates=[
        {"name": "Prompt > Answer", "qfmt": FRONT, "afmt": BACK},
        {"name": "Answer > Prompt", "qfmt": REV_FRONT, "afmt": REV_BACK},
    ],
    css=CSS,
    sort_field_index=0,
)


# --------------------------------------------------------------------------
# Card extraction
# --------------------------------------------------------------------------

class Builder:
    def __init__(self):
        self.decks = {}
        self.guids = set()
        self.count = 0

    def deck(self, name):
        if name not in self.decks:
            self.decks[name] = genanki.Deck(stable_id("deck", name), name)
        return self.decks[name]

    def add(self, deck, exam, page_slug, context, prompt, answer, tier, reverse=""):
        if not prompt or not answer or tier == 0:
            return
        guid = genanki.guid_for(deck, plain(context), plain(prompt))
        if guid in self.guids:  # same prompt twice on a page: keep the first
            return
        self.guids.add(guid)
        tier = int(tier)
        note = genanki.Note(
            model=MODEL,
            fields=[prompt, answer, context, f"Tier {tier}", reverse],
            tags=[exam, f"tier{tier}", page_slug],
            guid=guid,
        )
        self.deck(deck).add_note(note)
        self.count += 1


def ref_tier(rule, h2, h3, star=None):
    default, overrides, star_tier, rest_tier = rule
    tier = default
    for pattern, t in overrides:
        if h3 and re.search(pattern, h3):
            tier = t
            break
        if re.search(pattern, h2):
            tier = t
    if tier == "star":
        return star_tier if star else rest_tier
    return tier


class Page:
    def __init__(self, builder, path, deck, exam, summaries):
        self.b = builder
        self.path = path
        self.deck = deck
        self.exam = exam
        self.slug = path.stem if path.stem != "index" else path.parent.name
        self.summaries = summaries
        self.blocks = read_page(path)
        self.title = next((d for k, d in self.blocks if k == "h1"), path.stem)
        self.book_other = BOOK_PAGES.get(self.title)
        self.rule = REFERENCE_PAGES.get(self.title, (3, [], None, None))

    def add(self, context, prompt, answer, tier, reverse=""):
        self.b.add(self.deck, self.exam, self.slug, context, prompt, answer, tier, reverse)

    def ctx(self, *parts):
        return " › ".join(to_html(p) for p in (self.title,) + parts if p)

    def run(self):
        h2 = h3 = ""
        book = chapters = None
        for kind, data in self._flatten(self.blocks):
            if kind == "h2":
                h2, h3 = data, ""
                m = BOOK_HEADING.match(data) if self.book_other is not None else None
                book, chapters = (m.group(1), m.group(2)) if m else (None, None)
                continue
            if kind in ("h3", "h4"):
                h3 = data
                continue
            if book:
                self.book_block(kind, data, book, chapters, h3)
            elif kind == "table":
                self.table(data, h2, h3)
            elif kind == "list":
                self.lists(data, h2, h3)

    def _flatten(self, blocks):
        """Admonition bodies are treated as a section titled by the admonition."""
        for kind, data in blocks:
            if kind == "admonition":
                title, inner = data
                yield ("h3", title)
                yield from self._flatten(inner)
            else:
                yield (kind, data)

    # -- books ---------------------------------------------------------------

    def book_block(self, kind, data, book, chapters, h3):
        name = f"{book} ({chapters})"
        in_outline = not h3 or h3.lower().startswith("outline")
        if kind == "list" and in_outline:
            top = [it for it in data if it[0] == 0]
            self.add(self.ctx(), f"{name}: main divisions",
                     list_html(top), outline_tier(book))
            for i, (lvl, _m, text) in enumerate(data):
                if lvl != 0:
                    continue
                children = []
                for it in data[i + 1:]:
                    if it[0] == 0:
                        break
                    children.append(it)
                if children:
                    self.add(self.ctx(name), f"{book} {to_html(text)} (contents)",
                             list_html(children, base_level=1), 3)
        elif kind == "list":
            refs = [BOLD_REF.match(t) for _l, _m, t in data if _l == 0]
            if refs and all(refs):
                for m in refs:
                    self.add(self.ctx(name, h3), f"{book}: {to_html(m.group(2))}",
                             f"<b>{book} {m.group(1)}</b>", 3, reverse=f"{book} {m.group(1)}")
            else:
                self.add(self.ctx(name), f"{book}: {to_html(h3)}", list_html(data), 3)
        elif kind == "table":
            self.table(data, name, h3, tier=3, prefix="Psalm " if book == "Psalms" else "")

    # -- tables --------------------------------------------------------------

    def table(self, rows, h2, h3, tier=None, prefix=""):
        header, body = rows[0], rows[1:]
        tier_col = header and header[0].strip().lower() == "tier"
        key_col = 1 if (tier_col or header[0].strip() == "#") else 0
        # A grouping column (blank on continuation rows) is not a usable prompt: key on the next one.
        if len(header) > key_col + 2 and any(not r[key_col].strip() for r in body if len(r) > key_col):
            key_col += 1
        labelled = len(header) - (1 if tier_col else 0) - (1 if header[0].strip() == "#" else 0) > 2
        reverse = self.title in REVERSE_PAGES
        for row in body:
            row = row + [""] * (len(header) - len(row))
            key = re.sub(r"\s*★\*?", "", row[key_col]).strip()
            key = re.sub(r"^(\*\*)?\d+\.\s*", r"\1", key)
            if prefix and re.fullmatch(r"[\d/*]+", key):
                key = prefix + key.replace("*", "")
            if not plain(key):
                continue
            others = [(header[i], row[i]) for i in range(len(header))
                      if i not in (key_col,) and not (tier_col and i == 0)
                      and not (header[i].strip() == "#") and row[i].strip()]
            if not others:
                continue
            if len(others) == 1 and not labelled:
                answer = to_html(others[0][1])
            else:
                answer = "<br>".join(
                    (f"<b>{to_html(h)}:</b> " if h.strip() else "") + to_html(v) for h, v in others)
            if tier_col:
                t = int(row[0]) if row[0].strip().isdigit() else 3
            elif tier is not None:
                t = tier
            elif self.book_other is not None:
                t = self.book_other
            else:
                t = ref_tier(self.rule, h2, h3, star="★" in row[key_col])
            rev = ""
            if reverse and len(others) >= 1 and len(plain(others[0][1])) <= 60:
                rev = to_html(others[0][1])
            book = re.sub(r"\*", "", key)
            if book in self.summaries:  # NT overview table: add the book's title line
                answer += f"<br><i>{to_html(self.summaries[book])}</i>"
            self.add(self.ctx(h2, h3), to_html(key), answer, t, reverse=rev)

    # -- lists ---------------------------------------------------------------

    def lists(self, items, h2, h3):
        if self.book_other is not None:
            tier = self.book_other
        else:
            tier = ref_tier(self.rule, h2, h3)
        top = [(i, t) for i, (lvl, _m, t) in enumerate(items) if lvl == 0]
        leads = [BOLD_LEAD.match(t) for _i, t in top]
        if top and sum(1 for m in leads if m) >= max(2, len(top) * 0.7):
            for (i, _t), m in zip(top, leads):
                if not m:
                    continue
                children = []
                for it in items[i + 1:]:
                    if it[0] == 0:
                        break
                    children.append(it)
                answer = to_html(m.group(2))
                if children:
                    answer += list_html(children, base_level=1)
                term = m.group(1).rstrip(":")
                if term in self.summaries:
                    answer += f"<br><i>{to_html(self.summaries[term])}</i>"
                self.add(self.ctx(h2, h3), to_html(term), answer, tier)
        else:
            heading = h3 or h2
            if heading:
                self.add(self.ctx(h2 if h3 else ""), to_html(heading), list_html(items), tier)


def book_subtitles(paths):
    """Book name -> its italic title line, from the book pages."""
    subs = {}
    for path in paths:
        blocks = read_page(path)
        for (k1, d1), (k2, d2) in zip(blocks, blocks[1:]):
            if k1 == "h2" and k2 == "para" and re.fullmatch(r"\*[^*].*[^*]\*", d2):
                m = BOOK_HEADING.match(d1)
                if m:
                    subs[m.group(1)] = d2[1:-1]
    return subs


def nav_pages():
    """(path, deck name, exam tag) for every page in mkdocs.yml's nav except the home page."""
    loader = yaml.SafeLoader
    loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda l, s, n: None)
    config = yaml.load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=loader)
    out = []

    def walk(node, trail):
        if isinstance(node, list):
            for item in node:
                walk(item, trail)
        elif isinstance(node, dict):
            for label, value in node.items():
                if isinstance(value, str):
                    out.append((value, trail + [label]))
                else:
                    walk(value, trail + [label])
        elif isinstance(node, str):
            out.append((node, trail))  # section index page: the section's own deck

    walk(config["nav"], [])
    pages = []
    for rel, trail in out:
        if rel == "index.md" or not trail:
            continue
        exam = re.sub(r"[^a-z]+", "-", trail[0].lower()).strip("-")
        pages.append((DOCS / rel, "::".join([ROOT_DECK] + trail), exam))
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    pages = nav_pages()
    subtitles = book_subtitles([p for p, _d, _e in pages])
    builder = Builder()
    for path, deck, exam in pages:
        Page(builder, path, deck, exam, subtitles).run()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(list(builder.decks.values())).write_to_file(str(args.out))
    print(f"Wrote {args.out.relative_to(ROOT)}: {builder.count} notes in {len(builder.decks)} decks")


if __name__ == "__main__":
    main()
