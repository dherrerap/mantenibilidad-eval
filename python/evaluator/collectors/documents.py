"""Documents and SQL of the app: *.sql files and the README (the one of the latest versioned documentation set, if there is one).
"""
import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_analysis as ra  # noqa: E402
from evaluator.common import RUBRIC, rel, walk


def read_sql_files(app, max_bytes=2_000_000):
    """[(relative path, text)] of the application's *.sql files (migrations, schema dumps), in a stable order."""
    out = []
    for p in walk(app):
        if p.suffix.lower() == ".sql" and p.stat().st_size <= max_bytes:
            out.append((rel(p, app), p.read_text(encoding="utf-8", errors="replace")))
    return sorted(out)


def readme_file(app):
    """The README that describes the app as it is: docs/<label>/README.md of the latest versioned set (rubric.json
    relational.doc_versions, e.g. docs/R2/README.md), else the README.md at the root, else the first README.md found."""
    for label in RUBRIC["relational"].get("doc_versions", []):
        f = ra.find_file(ra.version_dir(app, label), "README.md")
        if f:
            return f
    root = ra.find_file(app, "README.md")
    if root:
        return root
    return next((p for p in walk(app) if p.name.lower() == "readme.md"), None)


def readme_text(app):
    f = readme_file(app)
    return f.read_text(encoding="utf-8", errors="ignore") if f else ""
