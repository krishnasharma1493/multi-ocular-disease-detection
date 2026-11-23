# Eye-health reference corpus (NEI)

The patient chat explains general eye-health topics only from the documents in `sources/`, and shows which document and section supports each explanation. This folder holds those documents and the script that refreshes them.

> **Not yet reviewed.** The text has **not been reviewed by the project's ophthalmologist**. Every file says so in its `review_status`, and the chat shows that status next to each source.

## What is here

| Path | What it is |
|---|---|
| `sources/<slug>.md` | One National Eye Institute (NEI) patient page as Markdown: front matter, then the page's headings (`##` / `###`) and text. Committed, so the app works offline and reviewers can read the exact text the chat uses. |
| `fetch_nei.py` | Downloads the pages and rewrites `sources/`. |
| `../app/modules/knowledge/index.py` | Splits the sources into passages and indexes them with SQLite FTS5 (`build_index`, `ensure_index`, `search`). |

The nine pages, under `https://www.nei.nih.gov/eye-health-information/`:

| Slug | Page |
|---|---|
| `diabetic-retinopathy` | `eye-conditions-and-diseases/diabetic-retinopathy` |
| `glaucoma` | `eye-conditions-and-diseases/glaucoma` |
| `cataracts` | `eye-conditions-and-diseases/cataracts` |
| `nearsightedness-myopia` | `eye-conditions-and-diseases/nearsightedness-myopia` |
| `age-related-macular-degeneration` | `eye-conditions-and-diseases/age-related-macular-degeneration` |
| `dry-eye` | `eye-conditions-and-diseases/dry-eye` |
| `refractive-errors` | `eye-conditions-and-diseases/refractive-errors` |
| `low-vision` | `eye-conditions-and-diseases/low-vision` |
| `get-dilated-eye-exam` | `healthy-vision/finding-eye-doctor/get-dilated-eye-exam` |

In November 2026 NEI moved these pages from `/learn-about-eye-health/…` to `/eye-health-information/…`. The old addresses now answer `301`. The script uses the new addresses and does not follow redirects.

Each file starts with:

```yaml
---
title: Glaucoma
source: National Eye Institute (NEI)
url: https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/glaucoma
version: 2026-08-19        # the page's "Last updated" date
retrieved: 2026-11-23      # the day fetch_nei.py downloaded it
review_status: not reviewed by the project's ophthalmologist
---
```

## Reuse terms

These were checked on 23 Nov 2026 at <https://www.nei.nih.gov/web-policies> (which links to the [Copyright Policy](https://www.nei.nih.gov/web-policies/copyright-policy)) and <https://www.nei.nih.gov/disclaimers>.

- **Text may be copied.** The Copyright Policy says: "Unless otherwise noted, information on the National Eye Institute website is in the public domain. Public domain information may be freely distributed and copied." It also says most NEI web text "was prepared by employees of the United States Government and therefore is not subject to copyright. … You may freely copy that material."
- **Credit NEI.** As a courtesy, NEI asks for the credit **"Courtesy: National Eye Institute, National Institutes of Health (NEI/NIH)."** That credit is given here, and the chat shows "National Eye Institute (NEI)" with a link to the page for every source it cites.
- **No images or logos.** Graphics and photos "should not be reused without permission", and NEI logos "may not be used without specific written permission". The fetch script keeps **text only**: images, icons, figures and logos are dropped.
- **Copyrighted documents stay out.** Some pages link to copyright-protected documents, such as journal articles. Those are not fetched; only the nine pages above are.
- **Not medical advice; no endorsement.** The Disclaimers page says NEI does not intend "to provide specific medical advice" and "urges you to consult with a qualified physician for diagnosis and for answers to your personal questions". It also says NEI does not endorse products, and its material "may not be used for advertising or product endorsement purposes". The chat therefore never presents a source as a diagnosis, and it does not imply that NEI endorses RetinaScreen.

Re-check both pages whenever you refresh the corpus.

## Refresh the corpus

```bash
cd backend
python -m knowledge.fetch_nei                   # all nine pages, one request at a time
python -m knowledge.fetch_nei glaucoma dry-eye  # only some pages
git diff knowledge/sources                      # read exactly what changed
```

- The script sends a generic User-Agent (`RetinaScreen-knowledge-fetcher/1.0`) with no personal details, and waits 1 s between requests.
- Any status other than `200`, including a redirect, stops the run with the URL and its new location. If a page moved, update `PAGES` in `fetch_nei.py`, re-run it, and say so in the PR.
- The script also stops when a page has no "Last updated" date, or when almost no article text was found (the page layout changed).
- What is kept: the page title, the "At a glance" box, and the article's headings, paragraphs and lists. What is dropped: navigation, the jump menu, "Learn more …" links, images, promotional call-outs ("Featured Resource", "… Resources", awareness months), the sidebar and the footer. Parsing uses only the standard library's `html.parser`; NEI's Drupal markup has stable class names, so no new dependency is needed.
- Re-running the script resets `review_status` on the pages it rewrites, because new text has not been reviewed yet.

The app indexes the corpus by itself. At start-up, `ensure_index()` hashes `sources/*.md` and rebuilds `backend/knowledge.db` (setting `KNOWLEDGE_DB`, git-ignored) only when that hash changed. The index file is separate from `app.db`: it holds NEI text only, never patient data.

## How a reviewer approves an update

1. Open a PR that changes only `knowledge/sources/` (a refresh), or one that changes only `review_status` (an approval).
2. The project's ophthalmologist reads the changed files in the PR diff. These are the exact passages the chat will quote.
3. For each page they approve, change the front matter to, for example:
   ```yaml
   review_status: reviewed by Dr <name>, ophthalmologist, 2026-12-01
   ```
   They approve the PR in GitHub review, so the approval is recorded with their account.
4. After the merge, the next start-up re-indexes automatically, and the chat shows the new status under each source.

A page that is refreshed later goes back to `not reviewed by the project's ophthalmologist`. It needs a new review.
