"""NEI reference corpus and FTS5 index: splitting, ranking, query sanitising, rebuild-on-change, isolation."""
import ast
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.modules.knowledge import index as ix

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"
EXPECTED_SLUGS = {
    "diabetic-retinopathy", "glaucoma", "cataracts", "nearsightedness-myopia", "age-related-macular-degeneration",
    "dry-eye", "refractive-errors", "low-vision", "get-dilated-eye-exam",
}


@pytest.fixture()
def fixture_index(tmp_path, monkeypatch):
    """The tiny fixture corpus, indexed section by section (no merging: each section is far below 150 words)."""
    monkeypatch.setattr(ix, "MIN_WORDS", 1)
    db = tmp_path / "knowledge.db"
    assert ix.build_index(FIXTURES, db) == 8
    return db


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    db = tmp_path_factory.mktemp("knowledge") / "knowledge.db"
    ix.build_index(ix.SOURCES_DIR, db)
    return db


def test_passages_keep_metadata(fixture_index):
    hits = ix.search("glaucoma treatment", k=10, db_path=fixture_index)
    assert hits
    top = hits[0]
    assert top.doc_title == "Glaucoma"
    assert top.section == "Glaucoma > What's the treatment for glaucoma?"
    assert top.version == "2026-08-19"
    assert top.url == "https://example.org/fixture/glaucoma"
    assert top.review_status == "fixture text, not a medical source"
    assert "eye drops" in top.text and top.score > 0
    # A ### heading keeps its full path
    sections = {p.section for p in ix.search("cataract surgery", k=10, db_path=fixture_index)}
    assert "Cataracts > What's the treatment for cataracts? > Before surgery" in sections


def test_family_history_ranks_risk_passage_first(fixture_index):
    hits = ix.search("Does a family history of glaucoma raise my risk?", db_path=fixture_index)
    assert hits[0].section == "Glaucoma > Am I at risk for glaucoma?"
    assert "family history" in hits[0].text


@pytest.mark.parametrize("query", ['"glaucoma" OR *', "glaucoma NEAR(", "section: glaucoma", "^glaucoma -risk",
                                   "risk AND (", '"""', "*", "' OR 1=1 --"])
def test_fts_syntax_is_plain_text(fixture_index, query):
    hits = ix.search(query, db_path=fixture_index)  # must not raise sqlite3.OperationalError
    assert isinstance(hits, list)


def test_fts_syntax_query_still_finds_the_words(fixture_index):
    assert ix.search('"glaucoma" OR *', db_path=fixture_index)[0].doc_title == "Glaucoma"


@pytest.mark.parametrize("query", ["python program", "Write a Python program to sort a list", "What is 2 + 2?",
                                   "capital of France", "", "   ", "what is it"])
def test_unrelated_query_returns_nothing(fixture_index, query):
    assert ix.search(query, db_path=fixture_index) == []


def test_missing_index_returns_nothing(tmp_path):
    assert ix.search("glaucoma", db_path=tmp_path / "absent.db") == []


def test_ensure_index_rebuilds_only_on_change(tmp_path):
    sources = tmp_path / "sources"
    shutil.copytree(FIXTURES, sources)
    db = tmp_path / "knowledge.db"
    assert ix.ensure_index(sources, db) is True          # first build
    assert ix.ensure_index(sources, db) is False         # unchanged: no rebuild
    assert ix.ensure_index(sources, db) is False
    page = sources / "cataracts.md"
    page.write_text(page.read_text(encoding="utf-8").replace("very common", "extremely common"), encoding="utf-8")
    assert ix.ensure_index(sources, db) is True          # one file changed
    assert ix.ensure_index(sources, db) is False
    assert "extremely common" in ix.search("cataract lens", k=10, db_path=db)[0].text
    (sources / "glaucoma.md").unlink()                   # a removed file also counts as a change
    assert ix.ensure_index(sources, db) is True
    assert all(p.doc_title != "Glaucoma" for p in ix.search("glaucoma risk", k=10, db_path=db))


def test_passage_sizes_merge_small_and_split_long():
    words = lambda n, w: " ".join([w] * n)  # noqa: E731
    meta = {"title": "T", "version": "v", "url": "u", "review_status": "r"}
    body = "\n\n".join([
        "# T", "## A", words(40, "alpha"), "## B", words(50, "beta"), "## C", words(100, "gamma"),
        "## D", "\n\n".join(words(200, "delta") for _ in range(5)),  # 1000 words in 5 paragraphs
        "## E", words(20, "eps")])
    passages = ix.split_passages(meta, body)
    sizes = [len(p.text.split()) for p in passages]
    assert all(s <= ix.MAX_WORDS + 3 for s in sizes), sizes   # +3: headings of merged sections kept in the text
    assert passages[0].section == "T > A; B; C"                 # 40 + 50 + 100: merged until >= 150
    assert [p.section for p in passages[1:]] == ["T > D (part 1)", "T > D (part 2); E"]  # tiny tail joins the last
    assert "B\n" + words(50, "beta") in passages[0].text


def test_front_matter_is_required(tmp_path):
    (tmp_path / "bad.md").write_text("# No front matter\n\n## A\ntext\n", encoding="utf-8")
    with pytest.raises(ValueError, match="front matter"):
        ix.build_index(tmp_path, tmp_path / "k.db")


def test_knowledge_module_is_isolated_from_patient_data():
    """The index must never import screening/user models or open app.db."""
    tree = ast.parse(Path(ix.__file__).read_text(encoding="utf-8"))
    imported, names, strings = set(), set(), []
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(n) is not None}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            strings.append(node.value)
    assert not any(m.startswith(("app.modules.screenings", "app.modules.users", "app.modules.reviews",
                                 "app.models", "app.core.db", "sqlmodel")) for m in imported), imported
    assert not names & {"DATABASE_URL", "database_url", "engine", "Screening", "User", "ChatMessage"}
    assert not any("app.db" in s for s in strings)
    assert ix.settings.knowledge_db_path != Path(ix.settings.database_url.removeprefix("sqlite:///"))


# Real corpus ------------------------------------------------------------------------------------------------------

def test_real_corpus_files_and_front_matter():
    files = {p.stem: p for p in ix.SOURCES_DIR.glob("*.md")}
    assert set(files) == EXPECTED_SLUGS
    for slug, path in files.items():
        meta, body = ix._read_source(path)
        assert meta["source"] == "National Eye Institute (NEI)"
        assert re.fullmatch(r"https://www\.nei\.nih\.gov/\S+", meta["url"]), slug
        assert date.fromisoformat(meta["version"]) <= date.fromisoformat(meta["retrieved"]), slug
        assert meta["review_status"] == "not reviewed by the project's ophthalmologist"
        assert body.lstrip().startswith(f"# {meta['title']}") and "\n## " in body, slug
        assert "<" not in body and "](" not in body, f"{slug}: HTML or links left in the text"


def test_real_corpus_passage_sizes(real_index):
    for path in ix.SOURCES_DIR.glob("*.md"):
        for p in ix.split_passages(*ix._read_source(path)):
            assert 100 <= len(p.text.split()) <= ix.MAX_WORDS + 20, (p.section, len(p.text.split()))


def test_real_corpus_diabetes_retina(real_index):
    hits = ix.search("does diabetes damage the retina", db_path=real_index)
    assert hits and hits[0].doc_title == "Diabetic Retinopathy"


def test_real_corpus_cataract_treatment(real_index):
    hits = ix.search("how is cataract treated", db_path=real_index)
    assert hits and hits[0].doc_title == "Cataracts" and "treatment" in hits[0].section.lower()
    assert "surgery" in hits[0].text.lower()


def test_real_corpus_glaucoma_family_history(real_index):
    hits = ix.search("My father had glaucoma. Does that affect my risk?", db_path=real_index)
    assert hits[0].doc_title == "Glaucoma" and "risk" in hits[0].section.lower()
    assert ix.search("Write a Python program to sort a list", db_path=real_index) == []
