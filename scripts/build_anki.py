"""Build an Anki deck (anki/Ordination Study Guide.apkg) from the Markdown in docs/.

Every page in mkdocs.yml's nav becomes a subdeck, e.g. Ordination::Bible::Old Testament::Pentateuch.
Cards are tagged by exam (bible, theology, ...) and tier (tier1, tier2, tier3), using the same tier
rules as the website's tier filter (docs/assets/javascripts/tiers.js).

Every card front says what to answer (the grey "ask" line under the prompt). What becomes a card:
  - Table rows, phrased per table type (TABLES below). Question tables ("Tier | Question | Answer")
    use the question as written. Tables that list one thing per column (the four Gospels, the three
    missionary journeys) become one card per column and row.
  - Book outlines: each book's main divisions, and each division's contents.
  - "Key chapters"-style lists (items that start with a bold reference) become locate cards both ways.
  - Lists whose items start with a bold term ("**Christ** = ...") become one card per item; other
    lists become one card for the whole list under its heading.

Notes keep a stable ID, so re-importing after edits updates cards in place and keeps your review
history. Notes that a rebuild no longer produces are listed in anki/retired.tsv and sent as
"delete-me" cards, so they can be found and deleted after importing.

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
RETIRED = ROOT / "anki" / "retired.tsv"
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
SKIP_ADMONITIONS = {"Patterns"}  # study tips about the page itself, not content
BOOK_HEADING = re.compile(r"^(.*?)\s*\((\d+(?: \+ \d+)?)\)\s*$")
# A list item that starts with a bold reference: "**3** ...", "**6:24-26** ...", "**1 Samuel 3** ...".
BOLD_REF = re.compile(
    r"^\*\*((?:[123] )?[A-Z][a-z]+(?: of [A-Z][a-z]+)? )?([0-9](?:[0-9:,\- ]*[0-9])?)\*\*\s+(.*)$")
# A list item that starts with a bold term followed by a separator: "**Christ** = ...", "**Hesed:** ...".
BOLD_LEAD = re.compile(r"^\*\*([^*]+?)\*\*(?=[\s:=])\s*(?::|=|-|—)?\s*(.+)$")


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
# How each kind of table becomes cards
# --------------------------------------------------------------------------
#   key:       column used as the prompt (default: the first column that is not Tier or #)
#   prompt:    format for the prompt; {key} is the key cell, {<header>} any cell
#   ask:       what to answer
#   answer:    columns shown in the answer (default: all the others)
#   reverse:   ask for the reverse card (answer > prompt); the reverse prompt is the first
#              answer column
#   transpose: one card per (column, row): the column header is the prompt, the row label the ask
#   lists:     [(column, prompt, ask, ref column or None)]: each column is a separate list (no
#              row-wise cards); one card each
#   ordered:   (prompt, ask): also make one card asking for the whole key column in order
#   subtitle:  add the book's title line to the answer (the key cell is a book name)
#   id:        format of the note's stable ID, when it differs from the prompt cell (keeps review
#              history from earlier builds that keyed these rows differently)
TABLES = {
    ("Question", "Answer"): {"ask": ""},
    ("Era", "Books", "Summary"): {"prompt": "The Bible's storyline: {key}",
                                 "ask": "Which books cover this era, and what happens in it?"},
    ("#", "Commandments (Ex. 20)", "#", "Plagues (Ex. 7-12)"): {
        "lists": [("Commandments (Ex. 20)", "The Ten Commandments", "List them in order (Ex. 20).", None),
                  ("Plagues (Ex. 7-12)", "The ten plagues of Egypt", "List them in order (Ex. 7-12).", None)]},
    ("Feast (Lev. 23)", "Hebrew date", "Month", "Spiritual/prophetic significance"): {
        "prompt": "Feast: {key}", "ask": "When is it (Hebrew date, month), and what does it signify?"},
    ("Persian king", "Dates (BC)", "Associated with", "Primary achievement", "Key chapters"): {
        "prompt": "Persian king: {key}",
        "ask": "Dates, who is associated with him, what happened, and where in Scripture?"},
    ("Book", "Psalms", "Primary theme/focus"): {"prompt": "Psalms, Book {key}",
                                                "ask": "Which psalms, and what is its focus?"},
    ("Psalm", "Key line (verse)"): {"prompt": "Psalm {key}", "ask": "Quote its key line.",
                                    "id": "Psalm {key}",
                                    "reverse": "Which psalm is this?"},
    ("Period", "Prophet", "Audience", "Approx. date (BC)"): {
        "key": "Prophet", "ask": "When did he prophesy (period, approx. date), and to whom?"},
    ("Period", "Approx. date (BC)", "Key events", "Where"): {
        "key": "Key events", "ask": "When (approx. date BC), and where in Scripture?",
        "id": "{Approx. date (BC)}",
        "answer": ["Approx. date (BC)", "Period", "Where"]},
    ("Covenant", "Key passages", "Parties / mediator", "Promise and content", "Sign"): {
        "prompt": "Covenant: {key}", "ask": "Key passages, parties, promise, and sign?"},
    ("Person", "Where", "Significance"): {
        "ask": "Who is this? Where in Scripture, and why significant?"},
    ("Person / group", "Where", "Significance"): {
        "ask": "Who is this? Where in Scripture, and why significant?"},
    ("Place", "Where", "Significance"): {"ask": "Where in Scripture, and what happened here?"},
    ("Passage", "Location", "Notes"): {"ask": "Where is it? (book and chapter)",
                                       "reverse": "What passage is this?"},
    ("Event", "Location", "Date (where asterisked)"): {
        "ask": "Where is it (book and chapter), and when?", "reverse": "What event is this?"},
    ("Division", "Books", "#"): {"prompt": "NT division: {key}", "ask": "Which books are in it?",
                                 "answer": ["Books"]},
    ("#", "Book", "Author", "Date (AD, approx.)", "Summary"): {
        "ask": "Author, approximate date, and one-line summary?", "subtitle": True},
    ("Event", "Matt.", "Mark", "Luke", "John"): {
        "ask": "Where is it in each Gospel? (chapters)"},
    ("", "Matthew", "Mark", "Luke", "John"): {"transpose": True},
    ("Parable", "Where"): {"prompt": "Parable: {key}", "ask": "Where is it?"},
    ("Miracle", "Where", "Shows"): {"prompt": "Miracle: {key}",
                                    "ask": "Where is it, and what does it show?"},
    ("Sign", "Ch.", '"I am..."', "Ref."): {
        "lists": [("Sign", "The seven signs in John", "List them in order, with chapters.", "Ch."),
                  ('"I am..."', 'The seven "I am" sayings in John', "List them in order, with references.", "Ref.")],
        "locate": [("Sign", "Ch.", "Which chapter of John?", "John {v}", "What sign is here?"),
                   ('"I am..."', "Ref.", "Where in John?", "John {v}", 'What "I am" saying is here?')]},
    ("Sermon", "Ref.", "Audience", "Distinctive"): {
        "prompt": "Sermon: {key}", "ask": "Where in Acts, to whom, and what is distinctive?"},
    ("Date (AD)", "Event", "Acts", "Letters written"): {
        "key": "Event", "ask": "When (AD), where in Acts, and which letters were written then?",
        "id": "{Date (AD)}"},
    ("", "First (Acts 13-14)", "Second (Acts 15:36-18:22)", "Third (Acts 18:23-21:16)"): {
        "transpose": True},
    ("#", "Passage", "Location"): {"ask": "Where is it? (book and chapter)",
                                   "reverse": "What passage is this?"},
    ("#", "Topic", "Passages"): {"prompt": "Topic: {key}",
                                 "ask": "Which passages teach on it? (bold = the main one)"},
    ("Section", "Topic", "WSC"): {"prompt": "{Topic}",
                                  "ask": "Which Shorter Catechism questions to memorize?",
                                  "answer": ["WSC"]},
    ("Hot topic", "Where it comes up"): {"prompt": "Hot topic: {key}",
                                         "ask": "Where does it come up (which doctrine)?"},
    ("", "Point", "In a sentence", "Two proof texts (ESV)"): {
        "prompt": "TULIP: {key}", "ask": "Name the point, define it, and give two proof texts."},
    ("#", "Step", "Meaning", "Key text"): {
        "prompt": "Ordo salutis: {key}", "ask": "What is this step, and a key text?",
        "ordered": ("The ordo salutis (order of salvation)", "List the steps in order.")},
    ("Point", "What to say", "Proof text (ESV)"): {
        "prompt": "Gospel outline: {key}", "ask": "What do you say here, and what is the proof text?",
        "ordered": ("A gospel outline", "Give its points in order.")},
    ("Tier", "Denomination", "Origins", "Distinctives"): {
        "ask": "Its origins and distinctives?"},
    ("Tier", "Event", "Date", "Significance"): {"ask": "Its date and significance?"},
    ("Tier", "Term", "Definition"): {"prompt": "Define: {key}", "ask": ""},
    ("Tier", "Person", "Dates", "Significance"): {
        "ask": "Identify: dates (century) and significance."},
}
QUESTION_TABLE = {"ask": ""}  # "Tier | Question | Answer ..." tables

# Row labels in transposed tables -> the question to ask.
TRANSPOSED_ASK = {
    "Jesus as": "How does it present Jesus?",
    "Audience": "Who was it written for?",
    "Key verse": "Its key verse(s)?",
    "Genealogy": "What kind of genealogy, if any?",
    "Marks": "What are its distinctive marks?",
    "Preparation": "Which chapters are the preparation?",
    "Public ministry": "Which chapters are the public ministry?",
    "Passion": "Which chapters are the passion?",
    "Date": "When was it?",
    "Companions": "Who went with Paul?",
    "Sent from": "Where was Paul sent from?",
    "Route": "What was the route?",
    "Key events": "What were the key events?",
    "Letters": "Which letters go with it?",
}
TRANSPOSED_PROMPT = {
    "First (Acts 13-14)": "Paul's first missionary journey (Acts 13-14)",
    "Second (Acts 15:36-18:22)": "Paul's second missionary journey (Acts 15:36-18:22)",
    "Third (Acts 18:23-21:16)": "Paul's third missionary journey (Acts 18:23-21:16)",
}

# Lists of "**term** text" items, by heading -> the question to ask about each term.
LEAD_ASK = [
    (r"Divisions|Pentateuch|History|Poetry|Prophets", "Summarize this book in one line."),
    (r"Names of Jesus", "What does this name mean?"),
    (r"Groupings", "Which books, and why are they grouped?"),
    (r"Sermons of Acts", "Explain this element of the apostles' sermons."),
    (r"Three parables", "Where is it, and what does it teach?"),
    (r"Three miracles", "Where is it, and what does it show?"),
    (r"covenant of grace relates", "How does the covenant of grace relate to this covenant?"),
    (r"Interpretive approaches", "What does this approach hold?"),
    (r"Millennial views", "What does this view hold?"),
    (r"Teaching", "Explain."),
    (r"Quotations", "Quote it."),
]


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


def list_html(items, base_level=0, ordered=False):
    """[(level, marker, text)] -> nested <ul> (or <ol> at the top level)."""
    top_tag = "ol" if ordered else "ul"
    out, depth = [], base_level - 1
    for level, _marker, text in items:
        while depth < level:
            out.append(f"<{top_tag if depth < base_level else 'ul'}>")
            depth += 1
        while depth > level:
            out.append("</ul>")
            depth -= 1
        out.append(f"<li>{to_html(text)}</li>")
    while depth >= base_level:
        out.append(f"</{top_tag}>" if depth == base_level else "</ul>")
        depth -= 1
    return "".join(out)


def stable_id(*parts):
    return int(hashlib.sha1("::".join(parts).encode()).hexdigest()[:8], 16)


def strip_marks(cell):
    """Drop the star (Chapell's list) and list numbering from a table cell."""
    cell = re.sub(r"\s*★\*?", "", cell).strip()
    return re.sub(r"^(\*\*)?\d+\.\s*", r"\1", cell)


# --------------------------------------------------------------------------
# Anki model
# --------------------------------------------------------------------------

CSS = """
.card { font-family: "Source Sans 3", "Segoe UI", Arial, sans-serif; font-size: 19px;
        line-height: 1.45; text-align: left; color: #222; background: #fff; padding: 0 6px; }
.nightMode.card, .night_mode .card { color: #ddd; background: #1e1e1e; }
.ctx { font-size: 13px; color: #888; margin-bottom: 10px; }
.prompt { font-size: 22px; font-weight: 600; }
.ask { font-size: 16px; font-weight: 400; font-style: italic; color: #6a6a6a; margin-top: 6px; }
.nightMode .ask, .night_mode .ask { color: #a8a8a8; }
.answer { margin-top: 4px; }
.answer ul, .answer ol { margin: 4px 0 4px 1.3em; padding: 0; }
.answer li { margin: 2px 0; }
.rev .ask { display: none; }
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
REV_BACK = '{{FrontSide}}<hr id="answer"><div class="answer rev">{{Prompt}}</div>'

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


def with_ask(prompt, ask):
    return prompt + (f'<div class="ask">{ask}</div>' if ask else "")


# --------------------------------------------------------------------------
# Card extraction
# --------------------------------------------------------------------------

class Builder:
    def __init__(self):
        self.decks = {}
        self.notes = {}  # guid -> deck name
        self.count = 0

    def deck(self, name):
        if name not in self.decks:
            self.decks[name] = genanki.Deck(stable_id("deck", name), name)
        return self.decks[name]

    def add(self, deck, exam, page_slug, context, prompt, answer, tier, ask="",
            reverse="", rev_ask="", key=None):
        """`key` identifies the note across rebuilds (defaults to the prompt)."""
        if not prompt or not answer or tier == 0:
            return
        guid = genanki.guid_for(deck, plain(context), plain(key if key is not None else prompt))
        if guid in self.notes:  # same prompt twice on a page: keep the first
            return
        self.notes[guid] = deck
        tier = int(tier)
        note = genanki.Note(
            model=MODEL,
            fields=[with_ask(prompt, ask), answer, context, f"Tier {tier}",
                    with_ask(reverse, rev_ask) if reverse else ""],
            tags=[exam, f"tier{tier}", page_slug],
            guid=guid,
        )
        self.deck(deck).add_note(note)
        self.count += 1

    def retire(self, guid, deck):
        """A note an earlier build made and this one no longer does: mark it for deletion."""
        note = genanki.Note(
            model=MODEL,
            fields=["(Retired card: delete it)",
                    "This card was replaced by a clearer one. In Browse, search "
                    "<b>tag:delete-me</b>, select all, and delete.", "", "", ""],
            tags=["delete-me"],
            guid=guid,
        )
        self.deck(deck).add_note(note)


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


# Whole lists (one card each), by heading -> the question to ask.
LIST_ASK = [
    (r"Torah|Former Prophets|Latter Prophets$|Writings", "Which books are in this division?"),
    (r"Chronological Order", "List them in rough chronological order."),
    (r"Twelve Apostles", "Name all twelve."),
    (r"Why the Order Matters", "Why does the order of the journeys matter?"),
]
SCRIPTURE_REF = re.compile(r"^(?:[123] )?[A-Z][a-z]+\.? \d+:\d+")


def list_ask(heading, ordered):
    for pattern, ask in LIST_ASK:
        if re.search(pattern, heading):
            return ask
    return "List them in order." if ordered else "List them."


def lead_ask(heading):
    for pattern, ask in LEAD_ASK:
        if re.search(pattern, heading):
            return ask
    return "Explain."


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

    def add(self, context, prompt, answer, tier, **kw):
        self.b.add(self.deck, self.exam, self.slug, context, prompt, answer, tier, **kw)

    def ctx(self, *parts):
        return " › ".join(to_html(p) for p in (self.title,) + parts if p)

    def run(self):
        h2 = h3 = ""
        book = chapters = None
        for kind, data in self._flatten(self.blocks):
            if kind == "h2" or (kind == "h3" and self.book_other is not None and BOOK_HEADING.match(data)):
                if kind == "h2":
                    h2 = data
                h3 = ""
                m = BOOK_HEADING.match(data) if self.book_other is not None else None
                book, chapters = (m.group(1), m.group(2)) if m else (None, None)
                continue
            if kind in ("h3", "h4"):
                h3 = data
                continue
            if book:
                self.book_block(kind, data, book, chapters, h2, h3)
            elif kind == "table":
                self.table(data, h2, h3)
            elif kind == "list":
                self.lists(data, h2, h3)

    def _flatten(self, blocks):
        """Admonition bodies are treated as a section titled by the admonition."""
        for kind, data in blocks:
            if kind == "admonition":
                title, inner = data
                if title in SKIP_ADMONITIONS:
                    continue
                yield ("h3", title)
                yield from self._flatten(inner)
            else:
                yield (kind, data)

    # -- books ---------------------------------------------------------------

    def book_block(self, kind, data, book, chapters, h2, h3):
        name = f"{book} ({chapters})"
        # A book under an h3 (the Pauline "Summaries") keeps its h2 in the context line.
        section = "" if BOOK_HEADING.match(h2 or "") else h2
        ctx_parts = (section, name)
        in_outline = not h3 or h3.lower().startswith("outline")
        if kind == "list" and in_outline:
            top = [it for it in data if it[0] == 0]
            # A mirror-image (chiastic) outline, "A ... B ... A' ...", only makes sense whole.
            chiasm = any(re.match(r"^\*\*[A-D]'?\*\*", t) for _l, _m, t in top)
            self.add(self.ctx(section), book, list_html(data if chiasm else top), outline_tier(book),
                     ask=(f"Outline its mirror-image structure ({chapters} chapters)." if chiasm
                          else f"Outline the main divisions ({chapters} chapters)."),
                     key=f"{name}: main divisions")
            if chiasm:
                return
            for i, (lvl, _m, text) in enumerate(data):
                if lvl != 0:
                    continue
                children = []
                for it in data[i + 1:]:
                    if it[0] == 0:
                        break
                    children.append(it)
                if children:
                    m = re.match(r"^\*\*([^*]+)\*\*\s*(.*)$", text)
                    prompt = (f"{book} {m.group(1)}: {to_html(m.group(2))}" if m
                              else f"{book}: {to_html(text)}")
                    self.add(self.ctx(*ctx_parts), prompt, list_html(children, base_level=1), 3,
                             ask="What is in this section?",
                             key=f"{book} {to_html(text)} (contents)")
        elif kind == "list":
            refs = [BOLD_REF.match(t) for _l, _m, t in data if _l == 0]
            # "**Beatitudes:** 5:3-12": a term located by a bare reference.
            located = [re.match(r"^\*\*([^*]+?):?\*\*:?\s+([0-9][0-9:,;\- ]*)$", t)
                       for _l, _m, t in data if _l == 0]
            if refs and any(located) and all(r or l for r, l in zip(refs, located)):
                for r, l in zip(refs, located):
                    if l:
                        where = f"{book} {l.group(2).strip()}"
                        term = to_html(l.group(1))
                    else:
                        where = f"{book} {r.group(2)}"
                        term = to_html(r.group(3))
                    self.add(self.ctx(*ctx_parts, h3), term, f"<b>{where}</b>", 3,
                             ask=f"Where is this in {book}?", reverse=where, rev_ask="What is here?",
                             key=f"{book}: {term}")
            elif refs and all(refs):
                for m in refs:
                    where = f"{m.group(1).strip()} {m.group(2)}" if m.group(1) else f"{book} {m.group(2)}"
                    self.add(self.ctx(*ctx_parts, h3), to_html(m.group(3)), f"<b>{where}</b>", 3,
                             ask=f"Where is this in {book}?" if not m.group(1) else "Where is this?",
                             reverse=where, rev_ask="What is here?",
                             key=f"{book}: {to_html(m.group(3))}")
            else:
                self.add(self.ctx(*ctx_parts), book, list_html(data), 3,
                         ask=f"{plain(h3)}: list them.", key=f"{book}: {to_html(h3)}")
        elif kind == "table":
            self.table(data, name, h3, tier=3)

    # -- tables --------------------------------------------------------------

    def table(self, rows, h2, h3, tier=None):
        header, body = rows[0], [r + [""] * (len(rows[0]) - len(r)) for r in rows[1:]]
        tier_col = header[0].strip().lower() == "tier"
        spec = TABLES.get(tuple(h.strip() for h in header))
        if spec is None:
            if not tier_col:
                raise SystemExit(f"{self.path.name}: no card spec for table {header}; add one to TABLES")
            spec = QUESTION_TABLE
        ctx = self.ctx(h2, h3)

        def row_tier(row, key_cell):
            if tier_col:
                return int(row[0]) if row[0].strip().isdigit() else 3
            if tier is not None:
                return tier
            if self.book_other is not None:
                return self.book_other
            return ref_tier(self.rule, h2, h3, star="★" in key_cell)

        if spec.get("lists"):
            for col, prompt, ask, ref_col in spec["lists"]:
                c = header.index(col)
                rc = header.index(ref_col) if ref_col else None
                items = [(0, "1.", strip_marks(r[c]) + (f" ({r[rc].strip()})" if rc is not None else ""))
                         for r in body if r[c].strip()]
                self.add(ctx, prompt, list_html(items, ordered=True), row_tier(body[0], ""),
                         ask=ask, key=to_html(col))
            for col, ref_col, ask, fmt, rev_ask in spec.get("locate", []):
                c, rc = header.index(col), header.index(ref_col)
                for r in body:
                    where = fmt.format(v=plain(r[rc]))
                    self.add(ctx, to_html(r[c]), f"<b>{where}</b>", row_tier(r, ""), ask=ask,
                             reverse=where, rev_ask=rev_ask)
            return

        if spec.get("transpose"):
            for col in range(1, len(header)):
                entity = header[col].strip()
                for r in body:
                    attr = plain(r[0])
                    if not r[col].strip():
                        continue
                    self.add(ctx, TRANSPOSED_PROMPT.get(entity, entity), to_html(r[col]),
                             row_tier(r, ""), ask=TRANSPOSED_ASK.get(attr, f"{attr}?"),
                             key=f"{entity}: {attr}")
            return

        cols = [h.strip() for h in header]
        if "key" in spec:
            key_col = cols.index(spec["key"])
        else:
            key_col = 1 if tier_col or cols[0] == "#" else 0
        show = spec.get("answer") or [h for i, h in enumerate(cols)
                                      if i != key_col and h != "#" and h.lower() != "tier"]
        order = []
        for r in body:
            key = strip_marks(r[key_col])
            if not plain(key):
                continue
            order.append((0, "1.", key))
            cells = {cols[i]: r[i] for i in range(len(cols))}
            parts = [(h, cells[h]) for h in show if cells.get(h, "").strip()]
            if not parts:
                continue
            if len(show) == 1:
                answer = to_html(parts[0][1])
            else:
                answer = "<br>".join(f"<b>{to_html(h)}:</b> {to_html(v)}" for h, v in parts)
            book = re.sub(r"\*", "", key)
            if spec.get("subtitle") and book in self.summaries:
                answer += f"<br><i>{to_html(self.summaries[book])}</i>"
            fmt = spec.get("prompt", "{key}")
            prompt = fmt.format(key=to_html(key), **{k: to_html(v) for k, v in cells.items() if k})
            rev = ""
            if spec.get("reverse") and parts:
                rev = to_html(parts[0][1])
            ident = spec.get("id", "{key}").replace("{key}", key)
            for k, v in cells.items():
                ident = ident.replace("{" + k + "}", v)
            self.add(ctx, prompt, answer, row_tier(r, r[key_col]), ask=spec.get("ask", ""),
                     reverse=rev, rev_ask=spec.get("reverse", ""), key=to_html(strip_marks(ident)))
        if spec.get("ordered") and order:
            prompt, ask = spec["ordered"]
            self.add(ctx, prompt, list_html(order, ordered=True),
                     row_tier(body[0], body[0][key_col]), ask=ask,
                     key=f"{self.title} {h2}: in order")

    # -- lists ---------------------------------------------------------------

    def lists(self, items, h2, h3):
        if self.book_other is not None:
            tier = self.book_other
        else:
            tier = ref_tier(self.rule, h2, h3)
        heading = h3 or h2
        top = [(i, t) for i, (lvl, _m, t) in enumerate(items) if lvl == 0]
        leads = [BOLD_LEAD.match(t) for _i, t in top]
        if top and sum(1 for m in leads if m) >= max(2, len(top) * 0.7):
            ask = lead_ask(heading)
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
                self.add(self.ctx(h2, h3), to_html(term), answer, tier,
                         ask="Quote it." if SCRIPTURE_REF.match(term) else ask, key=to_html(term))
        elif heading:
            ordered = items and items[0][1][0].isdigit()
            self.add(self.ctx(h2 if h3 else ""), to_html(heading), list_html(items, ordered=ordered),
                     tier, ask=list_ask(plain(heading), ordered), key=to_html(heading))


def book_subtitles(paths):
    """Book name -> its italic title line, from the book pages."""
    subs = {}
    for path in paths:
        blocks = read_page(path)
        for (k1, d1), (k2, d2) in zip(blocks, blocks[1:]):
            if k1 in ("h2", "h3") and k2 == "para" and re.fullmatch(r"\*[^*].*[^*]\*", d2):
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


def build():
    pages = nav_pages()
    subtitles = book_subtitles([p for p, _d, _e in pages])
    builder = Builder()
    for path, deck, exam in pages:
        Page(builder, path, deck, exam, subtitles).run()
    return builder


def read_retired():
    if not RETIRED.exists():
        return {}
    rows = [line.split("\t") for line in RETIRED.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {guid: deck for guid, deck in rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    builder = build()
    retired = {g: d for g, d in read_retired().items() if g not in builder.notes}
    for guid, deck in retired.items():
        builder.retire(guid, deck)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(list(builder.decks.values())).write_to_file(str(args.out))
    print(f"Wrote {args.out.relative_to(ROOT)}: {builder.count} notes in {len(builder.decks)} decks"
          f" (+{len(retired)} retired)")


if __name__ == "__main__":
    main()
