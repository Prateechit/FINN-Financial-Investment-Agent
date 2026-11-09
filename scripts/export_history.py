"""Export the Claude Code session(s) that built FINN into docs/ai-history/.

Writes the raw JSONL transcript (complete, machine-readable) and a readable Markdown rendering
(user prompts, assistant messages and tool calls; long tool outputs truncated).
"""
import json
import pathlib
import re
import sys

# Never publish credentials or personal identifiers that ended up in the transcript.
REDACT = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"gsk_[0-9A-Za-z]{20,}"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?:postgres(?:ql)?(?:\+psycopg)?://)[^\s\"'`]+"), "postgresql://[REDACTED]"),
    (re.compile(r"(?:ghp|gho|github_pat)_[0-9A-Za-z_]{20,}"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@gmail\.com"), "[REDACTED_EMAIL]"),
]


def _env_secrets() -> list[str]:
    """Literal values from backend/.env — key formats change, so pattern matching alone is not enough."""
    root = pathlib.Path(__file__).resolve().parent.parent
    vals = []
    for env in (root / "backend" / ".env", root / ".env.local", root / ".env"):
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                v = line.split("=", 1)[1].split(" #")[0].strip().strip("'\"")
                if len(v) >= 12:
                    vals.append(v)
    return vals


SECRETS = _env_secrets()


def redact(s: str) -> str:
    for v in SECRETS:
        s = s.replace(v, "[REDACTED_SECRET]")
    for rx, rep in REDACT:
        s = rx.sub(rep, s)
    return s

SRC = pathlib.Path.home() / ".claude" / "projects" / "C--Users-Prateechi"
OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "ai-history"
SESSIONS = sys.argv[1:] or ["c363bd54-6dbf-4695-9f84-97a9ce39aca0"]


def text_of(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for c in content or []:
        t = c.get("type")
        if t == "text":
            out.append(c["text"])
        elif t == "tool_use":
            inp = json.dumps(c.get("input"), ensure_ascii=False)
            out.append(f"**→ {c.get('name')}** `{inp[:600]}{'…' if len(inp) > 600 else ''}`")
        elif t == "tool_result":
            body = c.get("content")
            body = body if isinstance(body, str) else " ".join(x.get("text", "") for x in body or [] if isinstance(x, dict))
            out.append(f"<details><summary>result</summary>\n\n```\n{body[:1500]}{'…' if len(body) > 1500 else ''}\n```\n</details>")
    return out


OUT.mkdir(parents=True, exist_ok=True)
for sid in SESSIONS:
    src = SRC / f"{sid}.jsonl"
    (OUT / f"{sid}.jsonl").write_text(redact(src.read_text(encoding="utf-8")), encoding="utf-8")
    lines = [f"# Claude Code build session `{sid}`\n", "Exported from the local Claude Code transcript. Raw JSONL alongside.\n"]
    for raw in src.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        msg = ev.get("message") or {}
        role = msg.get("role") or ev.get("type")
        if role not in ("user", "assistant"):
            continue
        parts = text_of(msg.get("content"))
        if not parts:
            continue
        who = "🧑 User" if role == "user" and not any(p.startswith("<details>") for p in parts) else ("🤖 Claude" if role == "assistant" else "⚙️ Tool")
        lines.append(f"\n### {who}\n")
        lines.extend(p if len(p) < 8000 else p[:8000] + "\n…[truncated]" for p in parts)
    (OUT / f"{sid}.md").write_text(redact("\n\n".join(lines)), encoding="utf-8")
    print("exported", sid, (OUT / f"{sid}.md").stat().st_size // 1024, "KB")
