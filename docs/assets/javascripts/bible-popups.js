/*
 * Verse popups: Bible references in the page show the text of the Berean Standard Bible (public
 * domain) on hover (mouse) or on click/tap (any device).
 *
 * References are found in the rendered page, not marked in the Markdown:
 *   - "Rom. 13:1-7", "1 Cor. 15", "Pss. 2, 22, 110", "Gen. 12:1-3; 15; 17", "John 14:16-17, 26"
 *   - bare "3:15" or "1:18-3:20", read in the book of the section it sits in (a "Genesis (50)"
 *     heading, or a page titled with a book name), or the last book named in the same paragraph
 *   - bare chapter numbers in a table column headed with a book name ("Matt.", "Luke", "Psalm")
 * Text comes from assets/bible/bsb/NN.json (one file per book, loaded when first needed); see
 * scripts/build_bible.py.
 */
(function () {
  "use strict";

  var MAX_VERSES = 30;

  // [file number (1-66), display name, other names and abbreviations]. Numbered books are listed
  // without their number; the number in the text picks the book.
  var BOOKS = [
    [1, "Genesis", ["Gen", "Gn"]], [2, "Exodus", ["Ex", "Exod"]], [3, "Leviticus", ["Lev"]],
    [4, "Numbers", ["Num"]], [5, "Deuteronomy", ["Deut", "Dt"]], [6, "Joshua", ["Josh"]],
    [7, "Judges", ["Judg"]], [8, "Ruth", []], [9, "Samuel", ["Sam"], 2], [11, "Kings", ["Kgs"], 2],
    [13, "Chronicles", ["Chron", "Chr"], 2], [15, "Ezra", []], [16, "Nehemiah", ["Neh"]],
    [17, "Esther", ["Esth"]], [18, "Job", []], [19, "Psalms", ["Psalm", "Pss", "Ps"]],
    [20, "Proverbs", ["Prov"]], [21, "Ecclesiastes", ["Eccles", "Eccl"]],
    [22, "Song of Songs", ["Song of Solomon", "Song"]], [23, "Isaiah", ["Isa"]],
    [24, "Jeremiah", ["Jer"]], [25, "Lamentations", ["Lam"]], [26, "Ezekiel", ["Ezek"]],
    [27, "Daniel", ["Dan"]], [28, "Hosea", ["Hos"]], [29, "Joel", []], [30, "Amos", []],
    [31, "Obadiah", ["Obad"]], [32, "Jonah", []], [33, "Micah", ["Mic"]], [34, "Nahum", ["Nah"]],
    [35, "Habakkuk", ["Hab"]], [36, "Zephaniah", ["Zeph"]], [37, "Haggai", ["Hag"]],
    [38, "Zechariah", ["Zech"]], [39, "Malachi", ["Mal"]], [40, "Matthew", ["Matt", "Mt"]],
    [41, "Mark", ["Mk"]], [42, "Luke", ["Lk"]], [43, "John", ["Jn"], 3], [44, "Acts", []],
    [45, "Romans", ["Rom"]], [46, "Corinthians", ["Cor"], 2], [48, "Galatians", ["Gal"]],
    [49, "Ephesians", ["Eph"]], [50, "Philippians", ["Phil"]], [51, "Colossians", ["Col"]],
    [52, "Thessalonians", ["Thess"], 2], [54, "Timothy", ["Tim"], 2], [56, "Titus", ["Tit"]],
    [57, "Philemon", ["Philem", "Phlm"]], [58, "Hebrews", ["Heb"]], [59, "James", ["Jas"]],
    [60, "Peter", ["Pet"], 2], [65, "Jude", []], [66, "Revelation", ["Rev"]],
  ];
  // Chapters per book, by file number; a "chapter" beyond these is not a reference ("Ezra 458").
  var CHAPTER_COUNTS = [0, 50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42, 150,
    31, 12, 8, 66, 52, 5, 48, 12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4, 28, 16, 24, 21, 28, 16, 16, 13,
    6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1, 1, 22];
  // 1-3 John are files 62-64, not 43 + n.
  var NUMBERED_JOHN = { 1: 62, 2: 63, 3: 64 };
  var SINGLE_CHAPTER = { 31: 1, 57: 1, 63: 1, 64: 1, 65: 1 };

  var byName = {}; // lower-case name -> book entry
  var names = [];
  BOOKS.forEach(function (b) {
    [b[1]].concat(b[2]).forEach(function (n) {
      byName[n.toLowerCase()] = b;
      names.push(n);
    });
  });
  names.sort(function (a, b) { return b.length - a.length; });
  var NAME_RE = names.map(function (n) { return n.replace(/ /g, "\\s+"); }).join("|");

  var NUM = "\\d+(?::\\d+)?(?:[-–]\\d+(?::\\d+)?)?";
  // A tail number followed by a book name ("; 2 Cor.") starts a new reference instead.
  var TAIL = "(?:\\s*[,;]\\s*" + NUM + "(?![\\d.])(?!\\.?\\s+(?:" + NAME_RE + ")\\b))*";
  var REF_RE = new RegExp("(?:\\b([123])\\s*)?\\b(" + NAME_RE + ")\\.?\\s+(" + NUM + TAIL + ")(?![\\w:])", "g");
  var BARE_RE = new RegExp("(?<![\\w:.–-])(\\d+:\\d+(?:[-–]\\d+(?::\\d+)?)?" + TAIL + ")(?![\\w:])", "g");
  var CHAPTERS_RE = new RegExp(NUM, "g");

  /** Resolve a book name (and optional number) to [file number, display name], or null. */
  function book(num, name) {
    var b = byName[name.replace(/\s+/g, " ").toLowerCase()];
    if (!b) return null;
    var count = b[3] || 0;
    if (count) {
      if (!num) return b[1] === "John" ? [43, "John"] : null; // "Kings 3" alone is not a reference
      if (+num > count) return null;
      var file = b[1] === "John" ? NUMBERED_JOHN[num] : b[0] + (+num - 1);
      return [file, num + " " + b[1]];
    }
    if (num) return null;
    return [b[0], b[1]];
  }

  /**
   * Split "13:1-7, 9; 15; 16:2" into segments, each {c1, v1, c2, v2, text} (v = 0: whole chapter).
   * After a verse reference, ", 9" is more verses in the same chapter; otherwise it is a chapter.
   */
  function segments(spec, bookFile) {
    var out = [];
    var re = /([,;]?)\s*(\d+)(?::(\d+))?(?:[-–](\d+)(?::(\d+))?)?/g;
    var m;
    var last = null;
    var single = SINGLE_CHAPTER[bookFile];
    while ((m = re.exec(spec))) {
      var sep = m[1];
      var a = +m[2], av = m[3] ? +m[3] : 0, b = m[4] ? +m[4] : 0, bv = m[5] ? +m[5] : 0;
      var seg;
      if (av && b && !bv && b < av) {
        seg = { c1: a, v1: av, c2: b, v2: 0 }; // "1:14-10": 1:14 to the end of chapter 10
      } else if (av) {
        seg = { c1: a, v1: av, c2: bv ? b : a, v2: bv ? bv : (b || av) };
      } else if (bv) {
        seg = { c1: a, v1: 1, c2: b, v2: bv }; // "1-4:13"
      } else if (sep === "," && last && last.v1) {
        seg = { c1: last.c2, v1: a, c2: last.c2, v2: b || a };
      } else if (single) {
        seg = { c1: 1, v1: a, c2: 1, v2: b || a };
      } else {
        seg = { c1: a, v1: 0, c2: b || a, v2: 0 };
      }
      seg.text = m[0].replace(/^[,;]?\s*/, "");
      seg.start = m.index + m[0].length - seg.text.length;
      out.push(seg);
      last = seg;
    }
    return out;
  }

  // ---- Tagging ----------------------------------------------------------------------------

  var SKIP = "A, CODE, PRE, H1, H2, H3, H4, H5, H6, BUTTON, SCRIPT, STYLE, .bref, .tier-control, .tier-banner, .headerlink";
  var BOOK_HEADING = /^(.*?)\s*\(\d+(?: \+ \d+)?\)\s*¶?$/;

  function headingBook(text) {
    var m = BOOK_HEADING.exec(text.trim());
    var name = (m ? m[1] : text).replace(/¶/g, "").trim().replace(/\.$/, "");
    var nm = /^([123])\s+(.*)$/.exec(name);
    return nm ? book(nm[1], nm[2]) : book(null, name);
  }

  function makeRef(doc, text, bookInfo, seg) {
    var span = doc.createElement("span");
    span.className = "bref";
    span.tabIndex = 0;
    span.setAttribute("role", "button");
    span.dataset.book = bookInfo[0];
    span.dataset.name = bookInfo[1];
    span.dataset.ref = [seg.c1, seg.v1, seg.c2, seg.v2].join(".");
    span.textContent = text;
    return span;
  }

  /** Replace matches in one text node. `found` returns [{index, length, book, segs}]. */
  function wrap(node, matches) {
    if (!matches.length) return;
    var doc = node.ownerDocument;
    var frag = doc.createDocumentFragment();
    var text = node.nodeValue;
    var pos = 0;
    matches.forEach(function (m) {
      m.segs.forEach(function (seg) {
        var start = m.index + seg.offset;
        if (start < pos) return;
        frag.appendChild(doc.createTextNode(text.slice(pos, start)));
        frag.appendChild(makeRef(doc, text.substr(start, seg.length), m.book, seg));
        pos = start + seg.length;
      });
    });
    frag.appendChild(doc.createTextNode(text.slice(pos)));
    node.parentNode.replaceChild(frag, node);
  }

  /** Segments with offsets relative to the start of `full`, where `spec` begins at `specAt`. */
  function placed(spec, specAt, bookInfo, firstText) {
    var segs = segments(spec, bookInfo[0]);
    segs.forEach(function (s, i) {
      s.offset = specAt + s.start;
      s.length = s.text.length;
      if (i === 0 && firstText) {
        // The first segment's link covers the book name too ("Rom. 13:1-7").
        s.offset = 0;
        s.length = specAt + s.start + s.text.length;
      }
    });
    return segs;
  }

  /** Segments of `spec` in `bookInfo`, or null if any chapter is beyond the end of the book. */
  function fits(spec, specAt, bookInfo, firstText) {
    var segs = placed(spec, specAt, bookInfo, firstText);
    var max = CHAPTER_COUNTS[bookInfo[0]];
    return segs.every(function (s) { return s.c1 <= max && s.c2 <= max; }) ? segs : null;
  }

  function scanText(node, ctx) {
    var text = node.nodeValue;
    var matches = [];
    var m, segs;
    function taken(pos) {
      return matches.some(function (x) { return pos >= x.index && pos < x.end; });
    }
    REF_RE.lastIndex = 0;
    while ((m = REF_RE.exec(text))) {
      var b = book(m[1], m[2]);
      if (!b || !(segs = fits(m[3], m[0].length - m[3].length, b, true))) continue;
      matches.push({ index: m.index, end: m.index + m[0].length, book: b, segs: segs });
      ctx.last = b;
    }
    var named = matches.slice();
    var before = ctx.before; // last book named earlier in this paragraph or cell
    // A bare "3:15" belongs to the book of its table column or section, else the book named just
    // before it; the first of these in which the reference exists wins.
    function candidates(pos) {
      var prev = null;
      named.forEach(function (x) { if (x.index < pos) prev = x.book; });
      return [ctx.column, ctx.section, prev, before].filter(Boolean);
    }
    BARE_RE.lastIndex = 0;
    while ((m = BARE_RE.exec(text))) {
      var at = m.index;
      if (taken(at)) continue;
      var spec = m[1];
      var pick = null;
      candidates(at).some(function (b) { return (segs = fits(spec, 0, b, false)) && (pick = b); });
      if (pick) matches.push({ index: at, end: at + m[0].length, book: pick, segs: segs });
    }
    ctx.before = ctx.last;
    if (ctx.column && !/[A-Za-z]{3}/.test(text.replace(/\(.*?\)/g, ""))) {
      // A bare chapter column ("3", "9-11", "(16:19)", "6/38") under a book heading.
      CHAPTERS_RE.lastIndex = 0;
      while ((m = CHAPTERS_RE.exec(text))) {
        if (taken(m.index) || !(segs = fits(m[0], 0, ctx.column, false))) continue;
        matches.push({ index: m.index, end: m.index + m[0].length, book: ctx.column, segs: segs });
      }
    }
    matches.sort(function (a, b) { return a.index - b.index; });
    wrap(node, matches);
  }

  /** The book named by a table cell's column heading, if any. */
  function columnBook(cell) {
    var table = cell.closest("table");
    if (!table) return null;
    var idx = Array.prototype.indexOf.call(cell.parentNode.children, cell);
    var th = table.querySelectorAll("thead th")[idx];
    return th ? headingBook(th.textContent) : null;
  }

  function tag(article) {
    var pageBook = headingBook((article.querySelector("h1") || {}).textContent || "");
    var section = pageBook;
    Array.prototype.forEach.call(article.children, function (block) {
      if (block.tagName === "H2") {
        section = headingBook(block.textContent) || (BOOK_HEADING.test(block.textContent.trim()) ? null : pageBook);
        return;
      }
      var units = block.matches("table, .md-typeset__scrollwrap")
        ? block.querySelectorAll("td")
        : block.matches("ul, ol") ? block.querySelectorAll("li") : [block];
      Array.prototype.forEach.call(units, function (unit) {
        var ctx = { section: section, last: null, column: unit.tagName === "TD" ? columnBook(unit) : null };
        var walker = document.createTreeWalker(unit, NodeFilter.SHOW_TEXT, {
          acceptNode: function (n) {
            if (!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            if (n.parentElement.closest(SKIP)) return NodeFilter.FILTER_REJECT;
            // A nested list item is scanned as its own unit.
            var li = n.parentElement.closest("li");
            if (unit.tagName === "LI" && li !== unit) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
          },
        });
        var nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(function (n) { scanText(n, ctx); });
      });
    });
  }

  // ---- Popup --------------------------------------------------------------------------------

  var cache = {};
  var base = (function () {
    var s = document.querySelector('script[src*="bible-popups.js"]');
    return s ? new URL("../bible/bsb/", s.src).href : "assets/bible/bsb/";
  })();

  function load(file) {
    if (!cache[file]) {
      var name = (file < 10 ? "0" : "") + file + ".json";
      cache[file] = fetch(base + name).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
    }
    return cache[file];
  }

  function label(el) {
    var p = el.dataset.ref.split(".").map(Number);
    var c1 = p[0], v1 = p[1], c2 = p[2], v2 = p[3];
    var single = SINGLE_CHAPTER[+el.dataset.book];
    var s = el.dataset.name + " ";
    if (single) return s + v1 + (v2 !== v1 ? "–" + v2 : "");
    if (!v1) return s + c1 + (c2 !== c1 ? "–" + c2 : "");
    s += c1 + ":" + v1;
    if (c2 !== c1) return s + "–" + c2 + (v2 ? ":" + v2 : "");
    return s + (v2 !== v1 ? "–" + v2 : "");
  }

  function render(el, chapters) {
    var p = el.dataset.ref.split(".").map(Number);
    var c1 = p[0], v1 = p[1] || 1, c2 = p[2], v2 = p[3];
    var html = [];
    var shown = 0, total = 0;
    var multi = c2 !== c1;
    for (var c = c1; c <= c2 && c <= chapters.length; c++) {
      var verses = chapters[c - 1];
      var from = c === c1 ? v1 : 1;
      var to = c === c2 && v2 ? Math.min(v2, verses.length) : verses.length;
      if (multi || !p[1]) html.push('<div class="bpop__ch">Chapter ' + c + "</div>");
      for (var v = from; v <= to; v++) {
        total++;
        if (shown >= MAX_VERSES) continue;
        shown++;
        var t = verses[v - 1];
        html.push('<sup>' + v + "</sup>" + (t ? escapeHtml(t) : '<i class="bpop__omit">(Not in the earliest manuscripts; omitted in the BSB.)</i>') + " ");
      }
    }
    if (total > shown) html.push('<div class="bpop__more">… ' + (total - shown) + " more verses</div>");
    return html.join("");
  }

  function escapeHtml(s) {
    return s.replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; });
  }

  var pop, current, hideTimer, showTimer;

  function ensurePop() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.className = "bpop";
    pop.setAttribute("role", "dialog");
    pop.hidden = true;
    pop.innerHTML = '<div class="bpop__head"><span class="bpop__ref"></span><span class="bpop__ver">BSB</span>' +
      '<button class="bpop__close" aria-label="Close">×</button></div><div class="bpop__body"></div>';
    pop.querySelector(".bpop__close").addEventListener("click", hide);
    pop.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    pop.addEventListener("mouseleave", function () { if (!pop.dataset.pinned) scheduleHide(); });
    document.body.appendChild(pop);
    return pop;
  }

  function show(el, pinned) {
    clearTimeout(hideTimer);
    ensurePop();
    current = el;
    if (pinned) pop.dataset.pinned = "1"; else delete pop.dataset.pinned;
    pop.querySelector(".bpop__ref").textContent = label(el);
    var body = pop.querySelector(".bpop__body");
    body.innerHTML = '<span class="bpop__loading">Loading…</span>';
    pop.hidden = false;
    place(el);
    load(+el.dataset.book).then(function (chapters) {
      if (current !== el) return;
      body.innerHTML = render(el, chapters);
      body.scrollTop = 0;
      place(el);
    }).catch(function () {
      if (current === el) body.textContent = "Could not load the text.";
    });
  }

  function place(el) {
    var r = el.getBoundingClientRect();
    var vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var w = Math.min(448, vw - 16);
    pop.style.width = w + "px";
    var left = Math.max(8, Math.min(r.left, vw - w - 8));
    pop.style.left = left + window.scrollX + "px";
    // Open below the reference if it fits, else above, else on the roomier side with a scroll.
    pop.style.maxHeight = "";
    var h = pop.offsetHeight;
    var spaceBelow = vh - r.bottom - 14, spaceAbove = r.top - 14;
    var below = h <= spaceBelow || (h > spaceAbove && spaceBelow >= spaceAbove);
    if (h > (below ? spaceBelow : spaceAbove)) {
      pop.style.maxHeight = Math.max(120, below ? spaceBelow : spaceAbove) + "px";
      h = pop.offsetHeight;
    }
    var top = below ? r.bottom + 6 : r.top - 6 - h;
    pop.style.top = top + window.scrollY + "px";
  }

  function hide() {
    clearTimeout(showTimer);
    if (pop) { pop.hidden = true; delete pop.dataset.pinned; }
    current = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 250);
  }

  var hoverable = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  document.addEventListener("mouseover", function (e) {
    if (!hoverable) return;
    var el = e.target.closest && e.target.closest(".bref");
    if (!el || (pop && pop.dataset.pinned)) return;
    clearTimeout(hideTimer);
    if (el === current && pop && !pop.hidden) return;
    clearTimeout(showTimer);
    showTimer = setTimeout(function () { show(el, false); }, 200);
  });
  document.addEventListener("mouseout", function (e) {
    if (!hoverable) return;
    var el = e.target.closest && e.target.closest(".bref");
    if (!el) return;
    clearTimeout(showTimer);
    if (pop && !pop.hidden && !pop.dataset.pinned) scheduleHide();
  });
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest(".bref");
    if (el) {
      e.preventDefault();
      if (el === current && pop && !pop.hidden && pop.dataset.pinned) hide();
      else show(el, true);
      return;
    }
    if (pop && !pop.hidden && !pop.contains(e.target)) hide();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") return hide();
    if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("bref")) {
      e.preventDefault();
      show(e.target, true);
    }
  });
  window.addEventListener("resize", function () { if (current && pop && !pop.hidden) place(current); });

  function init() {
    hide();
    var article = document.querySelector("article.md-content__inner");
    if (article) tag(article);
  }

  if (window.document$ && window.document$.subscribe) {
    window.document$.subscribe(init);
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }

  // For testing in the console.
  window.__biblePopups = { segments: segments, book: book, tag: tag, load: load };
})();
