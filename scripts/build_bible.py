"""Convert the Berean Standard Bible text into per-book JSON for the website's verse popups.

Download https://bereanbible.com/bsb.txt (public domain since April 30, 2023), then:

    python scripts/build_bible.py path/to/bsb.txt

Writes docs/assets/bible/bsb/01.json ... 66.json (Genesis ... Revelation). Each file is a list of
chapters, and each chapter a list of verse strings (verse 1 at index 0).
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "bible" / "bsb"
LINE = re.compile(r"^(.+?) (\d+):(\d+)\t(.*)$")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bsb_txt", type=Path)
    args = ap.parse_args()

    books = {}  # book name -> {chapter: {verse: text}}
    order = []
    for line in args.bsb_txt.read_text(encoding="utf-8-sig").splitlines():
        m = LINE.match(line)
        if not m:
            continue  # title and header lines
        book, ch, vs, text = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).strip()
        if book not in books:
            books[book] = {}
            order.append(book)
        books[book].setdefault(ch, {})[vs] = text
    if len(order) != 66:
        raise SystemExit(f"Expected 66 books, found {len(order)}")

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for i, book in enumerate(order, 1):
        chapters = []
        for ch in range(1, max(books[book]) + 1):
            verses = books[book].get(ch, {})
            chapters.append([verses.get(v, "") for v in range(1, max(verses, default=0) + 1)])
            total += len(verses)
        (OUT / f"{i:02d}.json").write_text(
            json.dumps(chapters, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(order)} books, {total} verses to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
