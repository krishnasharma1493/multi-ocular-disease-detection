"""Download the NEI patient pages and save each one as versioned Markdown in knowledge/sources/.

    cd backend && python -m knowledge.fetch_nei            # all pages
    cd backend && python -m knowledge.fetch_nei glaucoma   # only the slugs named

One request at a time, a generic User-Agent, and redirects are NOT followed: a page that moved
(any non-200 status) stops the run and names the URL, so nobody indexes a page they did not review.

Only the article text is kept (headings, paragraphs, lists). Navigation, footers, images, logos,
"learn more" links and promotional call-outs are dropped. The standard library's html.parser is
enough: NEI pages are well-formed Drupal markup with stable class names.
"""
import re
import sys
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

SOURCES_DIR = Path(__file__).resolve().parent / "sources"
BASE = "https://www.nei.nih.gov/eye-health-information/"
# slug -> path under BASE. NEI moved these pages from /learn-about-eye-health/ (301) in Nov 2026.
PAGES: dict[str, str] = {
    "diabetic-retinopathy": "eye-conditions-and-diseases/diabetic-retinopathy",
    "glaucoma": "eye-conditions-and-diseases/glaucoma",
    "cataracts": "eye-conditions-and-diseases/cataracts",
    "nearsightedness-myopia": "eye-conditions-and-diseases/nearsightedness-myopia",
    "age-related-macular-degeneration": "eye-conditions-and-diseases/age-related-macular-degeneration",
    "dry-eye": "eye-conditions-and-diseases/dry-eye",
    "refractive-errors": "eye-conditions-and-diseases/refractive-errors",
    "low-vision": "eye-conditions-and-diseases/low-vision",
    "get-dilated-eye-exam": "healthy-vision/finding-eye-doctor/get-dilated-eye-exam",
}
USER_AGENT = "RetinaScreen-knowledge-fetcher/1.0 (educational eye-screening project)"
REVIEW_STATUS = "not reviewed by an eye doctor"
DELAY_S = 1.0  # pause between requests

_BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "td", "th"}
_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "track"}
_SKIP_TAGS = {"script", "style", "noscript", "figure", "img", "svg", "button", "form", "iframe", "nav"}
# Containers inside the article that are not article text
_SKIP_CLASSES = ("c-link", "c-print-page", "c-jump-menu", "c-at-a-glance__image", "c-list__icon")


class FetchError(RuntimeError):
    pass


class _ArticleParser(HTMLParser):
    """Collects (kind, text) blocks from the at-a-glance box and the <article> of an NEI page.

    kind is "h2"/"h3"/... for headings, "li" for list items and "p" for paragraphs.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.last_updated = ""
        self.blocks: list[tuple[str, str]] = []
        self._stack: list[tuple[str, str | None]] = []  # (tag, "skip" | "capture" | "h1" | "updated" | None)
        self._skip = 0       # > 0 inside a dropped region
        self._capture = 0    # > 0 inside <article> or the at-a-glance content
        self._in_h1 = False
        self._in_updated = False
        self._buf: list[str] = []
        self._kind: str | None = None
        self._label = ""     # at-a-glance label such as "Diagnosis:", prefixed to its description
        self._in_link = 0
        self._unlinked = False  # the current block has text outside <a>; link-only blocks are "learn more" links

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text and self._kind == "label":
            self._label = text
        elif self._kind:
            if text and (self._unlinked or self._kind[0] == "h"):
                self.blocks.append((self._kind, f"{self._label} {text}" if self._label and self._kind == "p" else text))
            self._label = ""  # a label never outlives the block after it (even a dropped link-only one)
        self._buf, self._kind, self._unlinked = [], None, False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag == "br":
                self._buf.append(" ")
            return
        classes = (dict(attrs).get("class") or "").split()
        role: str | None = None
        if tag in _SKIP_TAGS or any(c in _SKIP_CLASSES for c in classes):
            role, self._skip = "skip", self._skip + 1
        elif tag == "article" or "c-at-a-glance__content" in classes:
            role, self._capture = "capture", self._capture + 1
        elif tag == "h1":
            role, self._in_h1 = "h1", True
        elif "c-last-updated" in classes:
            role, self._in_updated = "updated", True
        if tag == "a":
            role, self._in_link = "a", self._in_link + 1
        self._stack.append((tag, role))
        if self._skip or not self._capture:
            return
        if tag in _BLOCKS:
            self._flush()
            self._kind = tag if tag[0] == "h" else ("li" if tag in ("li", "dt", "dd") else "p")
        elif tag == "strong" and "c-at-a-glance__label" in classes:
            self._flush()
            self._kind = "label"

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not any(t == tag for t, _ in self._stack):
            return
        while self._stack:  # pop to the matching open tag (tolerates unclosed <p>/<li>)
            open_tag, role = self._stack.pop()
            if role == "skip":
                self._skip -= 1
            elif role == "capture":
                self._flush()
                self._capture -= 1
            elif role == "h1":
                self._in_h1 = False
            elif role == "updated":
                self._in_updated = False
            elif role == "a":
                self._in_link -= 1
            if open_tag == tag:
                break
        if tag in _BLOCKS or tag == "strong" and self._kind == "label":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.title += data
        if self._in_updated:
            self.last_updated += data
        if not self._skip and self._capture and self._kind is not None:
            self._buf.append(data)
            if not self._in_link and data.strip():
                self._unlinked = True


def _parse_version(last_updated: str, url: str) -> str:
    m = re.search(r"Last updated:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", last_updated)
    if not m:
        raise FetchError(f"No 'Last updated' date on {url}")
    return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()


def _to_markdown(blocks: list[tuple[str, str]], title: str) -> str:
    """Headings -> ## / ###, list items -> "- ", paragraphs as they are. Headings with no text are dropped."""
    lines: list[str] = [f"# {title}"]
    pending: list[tuple[int, str]] = []  # headings waiting for their first line of text
    prev = "h"
    for kind, text in blocks:
        if kind[0] == "h":
            level = 2 if kind in ("h1", "h2") else 3
            pending = [h for h in pending if h[0] < level] + [(level, text)]  # a same-level heading replaces an empty one
            prev = "h"
            continue
        for level, heading in pending:
            lines += ["", f"{'#' * level} {heading}"]
        if pending or not (kind == "li" and prev == "li"):
            lines.append("")  # blank line before a paragraph, and before the first item of a list
        pending = []
        lines.append(f"- {text}" if kind == "li" else text)
        prev = kind
    return "\n".join(lines).strip() + "\n"


def _is_promo_callout(heading: str) -> bool:
    h = heading.lower()
    return h.startswith("featured resource") or h.endswith(" resources") or h.endswith("month")


def _drop_promos(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    skipping = False
    for kind, text in blocks:
        if kind == "h2":
            skipping = _is_promo_callout(text)
        if not skipping:
            kept.append((kind, text))
    return kept


def extract(html: str, url: str) -> tuple[str, str, str]:
    """Return (title, version, markdown body) for one NEI page."""
    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    title = re.sub(r"\s+", " ", parser.title).strip()
    if not title:
        raise FetchError(f"No page title on {url}")
    blocks = _drop_promos(parser.blocks)
    if sum(len(t.split()) for _, t in blocks) < 150:
        raise FetchError(f"Almost no article text extracted from {url}: the page layout may have changed")
    return title, _parse_version(parser.last_updated, url), _to_markdown(blocks, title)


def render(title: str, url: str, version: str, retrieved: date, body: str) -> str:
    front = (f"---\ntitle: {title}\nsource: National Eye Institute (NEI)\nurl: {url}\nversion: {version}\n"
             f"retrieved: {retrieved.isoformat()}\nreview_status: {REVIEW_STATUS}\n---\n\n")
    return front + body


def fetch_all(slugs: list[str] | None = None, out_dir: Path = SOURCES_DIR) -> list[Path]:
    chosen = slugs or list(PAGES)
    unknown = [s for s in chosen if s not in PAGES]
    if unknown:
        raise FetchError(f"Unknown slug(s): {', '.join(unknown)}. Known: {', '.join(PAGES)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=False) as client:
        for i, slug in enumerate(chosen):
            url = BASE + PAGES[slug]
            if i:
                time.sleep(DELAY_S)
            resp = client.get(url)
            if resp.status_code != 200:
                moved = f" (moved to {resp.headers.get('location')})" if resp.is_redirect else ""
                raise FetchError(f"{url} returned HTTP {resp.status_code}{moved}. Update PAGES in fetch_nei.py.")
            title, version, body = extract(resp.text, url)
            path = out_dir / f"{slug}.md"
            path.write_text(render(title, url, version, date.today(), body), encoding="utf-8")
            written.append(path)
            print(f"{slug:34} {version}  {len(body.split()):5} words  {url}")
    return written


if __name__ == "__main__":
    try:
        fetch_all(sys.argv[1:] or None)
    except (FetchError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
