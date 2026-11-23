"""Full-text index of the NEI reference corpus (backend/knowledge/sources/*.md).

The index is an SQLite FTS5 table in its OWN database file (settings.KNOWLEDGE_DB), never app.db.
This module must not import screening or user models: patient records never enter this index.

    build_index(sources_dir, db_path)   split every Markdown file by ##/### heading and index the passages
    ensure_index()                      rebuild only when the corpus files changed (hash stored in the index)
    search(query, k)                    bm25-ranked passages, [] when nothing is relevant enough
"""
import hashlib
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core.config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)

SOURCES_DIR = BACKEND_DIR / "knowledge" / "sources"
MIN_WORDS = 150   # smaller sections are merged with the next one
MAX_WORDS = 600   # longer sections are split on paragraph boundaries
SECTION_WEIGHT = 4.0  # bm25 weight of the heading path vs 1.0 for body text
# bm25 gives ~0 weight to a word found in over half the passages ("treat*" is on every page), so the column
# weight alone cannot favour a heading match in a corpus this small. Each query word in the heading path adds:
SECTION_BONUS = 2.0
MIN_SCORE = 1.0       # minimum relevance score
MIN_COVERAGE = 0.5    # share of the query's content words a passage must contain
SCHEMA_VERSION = "1"  # bump when the table layout or splitting rules change, to force a rebuild

STOP_WORDS = frozenset("""
a about above after again against all also am an and any are aren as at be because been before being below
between both but by can cannot could did didn do does doesn doing don down during each few for from further get
gets got had has have having he her here hers herself him himself his how i if in into is isn it its itself just
know let like me might more most much must my myself no nor not now of off on once only or other our ours
ourselves out over own please same shall she should so some such tell than that the their theirs them themselves
then there these they this those through to too under until up very want was wasn we were what when where which
while who whom why will with would you your yours yourself yourselves s t ll re ve d m
""".split()) | frozenset(  # conversational words that say nothing about the eye-health topic
    "affect affects anything else explain hello hi latest mean meaning means mention mentioned mentions need ok okay "
    "question really recent report reports said say says show showed shown shows something tell thank thanks thing "
    "things think told".split())


@dataclass(frozen=True)
class Passage:
    doc_title: str
    section: str        # heading path, e.g. "Glaucoma > Am I at risk for glaucoma?"
    version: str        # the page's "Last updated" date
    url: str
    review_status: str
    text: str
    score: float = 0.0  # relevance (-bm25, higher is better); 0 when not from a search


# Parsing and splitting ---------------------------------------------------------------------------------------------

def _read_source(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, flags=re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.split(" #", 1)[0].strip()  # tolerate a trailing "# comment"
    missing = {"title", "url", "version", "review_status"} - meta.keys()
    if missing:
        raise ValueError(f"{path.name}: front matter lacks {', '.join(sorted(missing))}")
    return meta, m.group(2)


def _sections(title: str, body: str) -> list[tuple[str, str]]:
    """(heading path, text) for every ## / ### section that has text. Text before the first ## is kept too."""
    out: list[tuple[str, str]] = []
    h2 = h3 = None
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            out.append((" > ".join(x for x in (title, h2, h3) if x), text))
        buf.clear()

    for line in body.splitlines():
        if line.startswith("# "):  # the page title, already in the path
            continue
        if line.startswith("## ") or line.startswith("### "):
            flush()
            heading = line.lstrip("#").strip()
            if line.startswith("## "):
                h2, h3 = heading, None
            else:
                h3 = heading
        else:
            buf.append(line)
    flush()
    return out


def _words(text: str) -> int:
    return len(text.split())


def _split_long(text: str) -> list[str]:
    """Split on blank lines into chunks of at most MAX_WORDS words (a single huge paragraph stays whole)."""
    chunks: list[str] = []
    current: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        if current and _words("\n\n".join(current + [para])) > MAX_WORDS:
            chunks.append("\n\n".join(current))
            current = []
        current.append(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_passages(meta: dict[str, str], body: str) -> list[Passage]:
    """Passages of about MIN_WORDS..MAX_WORDS words. Tiny sections merge forward; long ones split."""
    title = meta["title"]
    pieces: list[tuple[str, str]] = []  # (heading path, text), each <= MAX_WORDS
    for path, text in _sections(title, body):
        parts = _split_long(text) if _words(text) > MAX_WORDS else [text]
        pieces += [(f"{path} (part {i + 1})" if len(parts) > 1 else path, p) for i, p in enumerate(parts)]

    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for piece in pieces:
        size = sum(_words(t) for _, t in current)
        if current and (size >= MIN_WORDS or size + _words(piece[1]) > MAX_WORDS):
            groups.append(current)
            current = []
        current.append(piece)
    if current:  # a tiny last group joins the previous one when it fits
        if groups and sum(_words(t) for _, t in current) < MIN_WORDS and \
                sum(_words(t) for _, t in groups[-1] + current) <= MAX_WORDS:
            groups[-1] += current
        else:
            groups.append(current)

    passages = []
    for group in groups:
        first = group[0][0]
        # Later headings are shown relative to the page title, and kept inside the text for the reader
        rest = [p.removeprefix(f"{title} > ") for p, _ in group[1:]]
        section = "; ".join([first, *rest])
        text = "\n\n".join([group[0][1], *(f"{h}\n{t}" for h, (_, t) in zip(rest, group[1:]))])
        passages.append(Passage(doc_title=title, section=section, version=meta["version"], url=meta["url"],
                                review_status=meta["review_status"], text=text))
    return passages


# Index ------------------------------------------------------------------------------------------------------------

def corpus_hash(sources_dir: Path) -> str:
    h = hashlib.sha256(SCHEMA_VERSION.encode())
    for path in sorted(sources_dir.glob("*.md")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)


def build_index(sources_dir: Path = SOURCES_DIR, db_path: Path | None = None) -> int:
    """(Re)build the FTS5 index from every *.md file in sources_dir. Returns the number of passages.

    The index is written to a temporary file and then swapped in, so a search never sees a half-built index.
    """
    sources_dir, db_path = Path(sources_dir), Path(db_path or settings.knowledge_db_path)
    files = sorted(sources_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No Markdown sources in {sources_dir}")
    passages = [p for f in files for p in split_passages(*_read_source(f))]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(f"{db_path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        con = sqlite3.connect(tmp)
        try:
            con.executescript("""
                CREATE VIRTUAL TABLE passages USING fts5(
                    section, text, doc_title UNINDEXED, version UNINDEXED, url UNINDEXED, review_status UNINDEXED,
                    tokenize = 'porter unicode61 remove_diacritics 2'
                );
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            con.executemany(
                "INSERT INTO passages (section, text, doc_title, version, url, review_status) VALUES (?, ?, ?, ?, ?, ?)",
                [(p.section, p.text, p.doc_title, p.version, p.url, p.review_status) for p in passages])
            con.execute("INSERT INTO meta VALUES ('corpus_hash', ?)", (corpus_hash(sources_dir),))
            con.commit()
        finally:
            con.close()
        os.replace(tmp, db_path)
    finally:
        tmp.unlink(missing_ok=True)
    logger.info("Knowledge index: %d passages from %d files -> %s", len(passages), len(files), db_path)
    return len(passages)


def _stored_hash(db_path: Path) -> str | None:
    if not db_path.is_file():
        return None
    try:
        con = _read_only(db_path)
        try:
            row = con.execute("SELECT value FROM meta WHERE key = 'corpus_hash'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def ensure_index(sources_dir: Path = SOURCES_DIR, db_path: Path | None = None) -> bool:
    """Build the index if it is missing or the corpus changed. Returns True when it rebuilt."""
    sources_dir, db_path = Path(sources_dir), Path(db_path or settings.knowledge_db_path)
    if _stored_hash(db_path) == corpus_hash(sources_dir):
        return False
    build_index(sources_dir, db_path)
    return True


# Search -----------------------------------------------------------------------------------------------------------

def query_terms(query: str) -> list[str]:
    """Lower-case words without stop words or duplicates. Nothing of the user's text reaches FTS as syntax."""
    seen: dict[str, None] = {}
    for word in re.findall(r"[^\W_]+", query.lower()):
        if word not in STOP_WORDS and len(word) > 1:  # single letters and digits ("2 + 2") carry no topic
            seen.setdefault(word, None)
    return list(seen)[:16]


def _fts_term(word: str) -> str:
    # Each word is a quoted string, so OR / NEAR / * / ^ / column filters in user text are plain words.
    # Words of 4+ letters also match as a prefix of the stemmed token ("treat" finds "treatment").
    return f'"{word}"*' if len(word) >= 4 else f'"{word}"'


def search(query: str, k: int = 4, *, db_path: Path | None = None) -> list[Passage]:
    """Top-k passages for a question, best first; [] when nothing is relevant enough.

    score = -bm25 (heading weighted above body) + SECTION_BONUS per query word in the heading path.
    A passage must contain at least MIN_COVERAGE of the query's words and reach MIN_SCORE.
    """
    terms = query_terms(query)
    db_path = Path(db_path or settings.knowledge_db_path)
    if not terms or k < 1 or not db_path.is_file():
        return []
    con = _read_only(db_path)
    try:
        rows = con.execute(
            f"""SELECT rowid, -bm25(passages, {SECTION_WEIGHT}, 1.0), section, text, doc_title, version, url,
                       review_status
                FROM passages WHERE passages MATCH ?""",
            (" OR ".join(_fts_term(t) for t in terms),)).fetchall()
        hits: dict[int, int] = {r[0]: 0 for r in rows}           # query words found anywhere
        in_heading: dict[int, int] = {r[0]: 0 for r in rows}     # query words found in the heading path
        for term in terms:
            for (rowid,) in con.execute("SELECT rowid FROM passages WHERE passages MATCH ?", (_fts_term(term),)):
                hits[rowid] += 1
            for (rowid,) in con.execute("SELECT rowid FROM passages WHERE passages MATCH ?",
                                        (f"section : {_fts_term(term)}",)):
                in_heading[rowid] += 1
    finally:
        con.close()
    needed = max(1, round(len(terms) * MIN_COVERAGE + 1e-9))
    scored = sorted(((bm25 + SECTION_BONUS * in_heading[rowid], rowid, rest) for rowid, bm25, *rest in rows
                     if hits[rowid] >= needed), key=lambda x: (-x[0], x[1]))
    return [Passage(section=sec, text=text, doc_title=doc, version=ver, url=url, review_status=rs, score=round(sc, 3))
            for sc, _, (sec, text, doc, ver, url, rs) in scored if sc >= MIN_SCORE][:k]
