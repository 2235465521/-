import json
from pathlib import Path

TRANSCRIPT = Path(
    r"C:\Users\20711\.cursor\projects\d-jiansuoPDF\agent-transcripts"
    r"\78cc2187-6abe-41b4-aead-3f9e629f8c25\78cc2187-6abe-41b4-aead-3f9e629f8c25.jsonl"
)
OUT = Path(__file__).resolve().parent / "_recovered"
TARGETS = {
    "config.py",
    "paths.py",
    "settings.py",
    "requirements.txt",
    "batch_download.py",
    "build_index.py",
    "pdf_discovery.py",
    "std_normalize.py",
    "sql_parser.py",
    "db.py",
}

OUT.mkdir(exist_ok=True)
found: dict[str, str] = {}
with TRANSCRIPT.open(encoding="utf-8") as f:
    for line in f:
        if "Write" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for part in obj.get("message", {}).get("content", []):
            if part.get("type") != "tool_use" or part.get("name") != "Write":
                continue
            inp = part.get("input", {})
            path = inp.get("path", "")
            base = Path(path).name
            if base in TARGETS and base not in found:
                found[base] = inp.get("contents", "")

for name, content in found.items():
    (OUT / name).write_text(content, encoding="utf-8")
    print(name, len(content))

print("total", len(found))
