import os
import mimetypes
import magic

RAW_PASTES_DIR = os.environ.get("RAW_PASTES_DIR", "/app/raw_pastes")
mimetypes.add_type("text/markdown", ".md")


def detect_content_type(filepath: str, content: str) -> str:
    if not content:
        return "empty"

    preview = content[:2000]
    content_stripped = preview.strip()
    if not content_stripped:
        return "blank"

    if content_stripped.startswith("{"):
        return "json"
    if content_stripped.startswith("<") and ("<html" in content[:200].lower() or "<!doctype" in content[:200].lower()):
        return "html"
    if content_stripped.startswith("<?xml") or (content_stripped.startswith("<") and not content_stripped.startswith("<!-")):
        if "<?xml" in content[:100] or "<!DOCTYPE" in content[:200]:
            return "xml"
    if "," in content[:200] and "\n" in content[:1000]:
        nl = content.index("\n") if "\n" in content else 0
        first_line = content[:nl] if nl else content[:200]
        if "," in first_line and any(kw in first_line.lower() for kw in ["id", "name", "date", "value", "type"]):
            return "csv"
    if content_stripped.startswith("import ") or content_stripped.startswith("from "):
        return "python"
    if "function " in content[:500] and ("var " in content[:500] or "let " in content[:500] or "const " in content[:500]):
        return "javascript"
    if content_stripped.startswith("#!/") or "#!/bin/" in content[:200]:
        return "shell"
    if "/* " in content[:500] or "#include" in content[:500]:
        return "c"
    if "class " in content[:500] and "{" in content[:500] and "public " in content[:500]:
        return "java"
    if content_stripped.startswith("# ") or content_stripped.startswith("## "):
        return "markdown"
    if content_stripped.startswith("<?php"):
        return "php"
    if content_stripped.startswith("SELECT ") or content_stripped.startswith("select "):
        return "sql"
    if content_stripped.startswith("CREATE ") or content_stripped.startswith("ALTER "):
        return "sql"
    if content_stripped.startswith("INSERT ") or content_stripped.startswith("UPDATE "):
        return "sql"
    if content_stripped.startswith("DELETE ") or content_stripped.startswith("DROP "):
        return "sql"
    if content_stripped.startswith("PROCEDURE ") or content_stripped.startswith("FUNCTION "):
        return "sql"

    try:
        mime = magic.from_file(filepath, mime=True)
        if mime.startswith("text/"):
            subtype = mime.split("/")[1]
            return subtype if subtype != "plain" else "text"
        if mime == "application/json":
            return "json"
        if mime == "text/csv":
            return "csv"
        if "xml" in mime:
            return "xml"
    except Exception:
        pass

    return "text"


def walk_pastes():
    if not os.path.exists(RAW_PASTES_DIR):
        return []

    files = []
    for source_dir in os.listdir(RAW_PASTES_DIR):
        source_path = os.path.join(RAW_PASTES_DIR, source_dir)
        if not os.path.isdir(source_path):
            continue
        for fname in os.listdir(source_path):
            fpath = os.path.join(source_path, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "id": fname,
                    "filename": fname,
                    "source": source_dir,
                    "path": fpath,
                    "size": stat.st_size,
                    "modified_at": str(stat.st_mtime),
                })
    return files