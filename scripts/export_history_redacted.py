"""Redacted, readable export of a Claude Code session window into docs/ai-history/.

Raw session records are never copied. Only the conversation is rendered — user prompts, assistant replies, tool calls
(name and input) and truncated tool results — and every string written is redacted:

  * literal values from backend/.env and .env.local, and any 12-character piece of one that is not public repository
    text (read here, never printed);
  * API keys and tokens: Google, Groq, Render, GitHub, OpenAI-style, Neon API, Vercel, JWTs, bearer tokens and
    KEY=/TOKEN=/SECRET=/PASSWORD= assignments;
  * PostgreSQL URLs, Neon passwords, endpoint hostnames and project ids;
  * Render service / owner / deploy ids, Vercel project / team ids and preview hostnames;
  * email addresses (except the public noreply@anthropic.com commit trailer);
  * the Windows username and home-directory paths, and public IPv4 addresses.

Embedded images and long base64 / binary payloads are dropped. Harness records (attachments, environment snapshots,
account records, API-request metadata), <system-reminder> blocks, IDE selections and the model's private reasoning
are not exported. Results of tool calls that touched a .env file are omitted.

Output is plain text with LF line endings on every platform: CRLF and lone carriage returns captured from tool output
become line breaks, trailing spaces/tabs are removed, and a line of exactly seven "=" (a decorative rule in extracted
PDF text, which Git reads as a merge-conflict marker) is dropped. Only whitespace and such rule lines change; the
counts are in the report.

    python scripts/export_history_redacted.py SESSION_ID START_ISO END_ISO OUT_STEM [continuation|earlier]

prints only counts — never a matched value.
"""
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECTS = pathlib.Path.home() / ".claude" / "projects"          # session files live in one subfolder per project
OUT = ROOT / "docs" / "ai-history"

HITS: collections.Counter = collections.Counter()


def _env_values() -> list[str]:
    vals = []
    for env in (ROOT / "backend" / ".env", ROOT / ".env.local", ROOT / ".env", ROOT / "frontend" / ".env"):
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    v = line.split("=", 1)[1].split(" #")[0].strip().strip("'\"")
                    if len(v) >= 6:
                        vals.append(v)
    return sorted(set(vals), key=len, reverse=True)       # longest first, so a URL goes before its parts


ENV_VALUES = _env_values()


def _env_fragments() -> list[str]:
    """Every 12-character piece of a .env value that is not already public text in the repository. A piece can leak
    without the whole value (a User-Agent sharing a token's readable prefix); generic pieces such as "postgresql:/"
    stay, because they occur in tracked files."""
    import subprocess
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    corpus = []
    for f in files:
        p = ROOT / f
        if f and not f.startswith("docs/ai-history/") and p.is_file() and p.stat().st_size < 2_000_000:
            try:
                corpus.append(p.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                pass
    corpus = "\n".join(corpus)
    frags = {v[i:i + 12] for v in ENV_VALUES if len(v) >= 12 for i in range(len(v) - 11)}
    return sorted(f for f in frags if f not in corpus)


ENV_FRAGMENTS = _env_fragments()
_ACCOUNT = pathlib.Path.home().name                       # the local account name — read at run time, never stored here
# The account name, and its 8.3 short form (first six letters + "~1"); a longer word it begins (a public handle) is kept.
USER = rf"(?i:{re.escape(_ACCOUNT)})(?![A-Za-z])|(?i:{re.escape(_ACCOUNT[:6])}~1)"

RULES = [  # (category, pattern, replacement) — applied in order
    ("binary/base64 payload", r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+|[A-Za-z0-9+/]{300,}={0,2}", "[binary data omitted]"),
    ("PostgreSQL URL", r"postgres(?:ql)?(?:\+\w+)?://[^\s\"'`<>]+", "postgresql://[REDACTED]"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{30,}|\bya29\.[0-9A-Za-z_\-]{20,}", "[REDACTED_GOOGLE_KEY]"),
    ("Groq key", r"\bgsk_[0-9A-Za-z]{20,}", "[REDACTED_GROQ_KEY]"),
    ("Render token", r"\brnd_[0-9A-Za-z]{16,}", "[REDACTED_RENDER_TOKEN]"),
    ("GitHub token", r"\b(?:gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,})", "[REDACTED_GH_TOKEN]"),
    ("OpenAI-style key", r"\bsk-(?:proj-|or-v1-|ant-)?[A-Za-z0-9_\-]{20,}", "[REDACTED_KEY]"),
    ("Neon credential", r"\bnpg_[A-Za-z0-9]{6,}|\bnapi_[A-Za-z0-9]{20,}", "[REDACTED_NEON_SECRET]"),
    ("Neon hostname", r"\b(?:[a-z0-9-]+\.)*ep-[a-z0-9-]+(?:\.[a-z0-9-]+)*\.neon\.tech\b|\b(?:[a-z0-9-]+\.)+(?:aws|azure|gcp)\.neon\.tech\b",
     "[REDACTED_NEON_HOST]"),
    ("Neon endpoint/project id", r"\bep-[a-z]+-[a-z]+-[a-z0-9]{6,}(?:-pooler)?\b|(?<=/projects/)[a-z0-9-]{8,}", "[REDACTED_NEON_ID]"),
    ("Render service/owner id", r"\b(?:srv|tea|usr|own|evm|dpl|dep|crn|cron|rdr|bgw|exs)-[a-z0-9]{16,}\b", "[REDACTED_RENDER_ID]"),
    ("Vercel token/id", r"\b(?:vercel_|vcp_)[A-Za-z0-9]{20,}|\b(?:prj|team)_[A-Za-z0-9]{16,}", "[REDACTED_VERCEL_ID]"),
    ("Vercel preview host", r"\b[a-z0-9-]+-(?i:prateechit)-\d+\.vercel\.app\b|\b(?i:prateechit)-\d{3,}\b", "[REDACTED_VERCEL_PREVIEW]"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "[REDACTED_JWT]"),
    ("bearer token", r"(?i)(?<=bearer )(?!\{)[A-Za-z0-9._\-]{16,}", "[REDACTED_TOKEN]"),
    ("secret assignment",
     r"(?i)((?:API_KEY|_TOKEN|SECRET|PASSWORD|PASSWD)=)(?![\"'`]?(?:\$|\{|<|\[REDACTED|os\.|change-me|none\b))[^\s\"'`&;|]{8,}",
     r"\1[REDACTED_SECRET]"),
    ("email address", r"[A-Za-z0-9._%+\-]+@(?!anthropic\.com\b)[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]"),
    ("local home path", r"(?i)\b[a-z]:[\\/]+users[\\/]+(?:" + USER + r")|/[a-z]/users/(?:" + USER + r")", "~"),
    ("Windows username", USER, "<user>"),
    ("public IPv4 address", r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b|1\.2\.3\.4\b)(?:\d{1,3}\.){3}\d{1,3}\b(?!\.\d)", "[REDACTED_IP]"),
]
RULES = [(cat, re.compile(rx), rep) for cat, rx, rep in RULES]


def redact(s: str) -> str:
    for v in ENV_VALUES:
        if v in s:
            HITS[".env value (literal)"] += s.count(v)
            s = s.replace(v, "[REDACTED_SECRET]")
    for f in ENV_FRAGMENTS:
        if f in s:
            HITS[".env value fragment"] += s.count(f)
            s = s.replace(f, "[REDACTED_SECRET_FRAGMENT]")
    for cat, rx, rep in RULES:
        s, n = rx.subn(rep, s)
        HITS[cat] += n
    return s


_DROP_TAGS = re.compile(r"<(system-reminder|ide_selection)>.*?</\1>", re.S)
_PASTED = re.compile(r"</?pasted_content[^>]*>")
_ENV_FILE = re.compile(r"(?<![\w-])\.env(?!\.example)\b|\.env\.local")


def clean_user_text(t: str) -> str:
    t = _DROP_TAGS.sub("", t)
    return _PASTED.sub("", t).strip()


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n…[{len(s) - n:,} characters truncated]"


def render_tool_use(x: dict) -> str:
    name, inp = x.get("name"), x.get("input") or {}
    if name in ("Bash", "PowerShell"):
        body = f"```\n{clip(str(inp.get('command', '')), 4000)}\n```"
        if inp.get("description"):
            body = f"_{inp['description']}_\n{body}"
    elif name == "Edit":
        body = (f"`{inp.get('file_path')}`\n\n```diff\n" + "\n".join("- " + ln for ln in clip(str(inp.get("old_string", "")), 6000).splitlines())
                + "\n" + "\n".join("+ " + ln for ln in clip(str(inp.get("new_string", "")), 6000).splitlines()) + "\n```")
    elif name == "Write":
        body = f"`{inp.get('file_path')}`\n\n```\n{clip(str(inp.get('content', '')), 12000)}\n```"
    else:
        body = f"```json\n{clip(json.dumps(inp, ensure_ascii=False, indent=1), 3000)}\n```"
    return f"**→ {name}**\n\n{body}"


def render_result(x: dict, touches_env: bool) -> str:
    body = x.get("content")
    parts, images = [], 0
    for item in [body] if isinstance(body, str) else (body or []):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, dict):
            images += 1
    text = "[output omitted: this tool call touched a .env file]" if touches_env else clip("\n".join(parts), 2500)
    if images:
        HITS["embedded image removed"] += images
        text += f"\n[{images} image(s) omitted]"
    text = text.replace("```", "ˋˋˋ")
    return f"<details><summary>result</summary>\n\n```\n{text}\n```\n</details>"


_RULE_LINE = re.compile(r"^={7}$")       # exactly seven "=": what Git's whitespace check reads as a conflict marker


def normalise(text: str) -> str:
    """LF line endings, no trailing spaces/tabs, no seven-"=" rule lines, one final newline. Whitespace-only apart from
    the rule lines; every change is counted in the report."""
    NORM["CRLF line endings converted"] += text.count("\r\n")
    text = text.replace("\r\n", "\n")
    NORM["lone carriage returns converted to line breaks"] += text.count("\r")
    text = text.replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        stripped = line.rstrip(" \t")
        if stripped != line:
            NORM["lines with trailing spaces/tabs trimmed"] += 1
        if _RULE_LINE.match(stripped):
            NORM['"=======" rule lines dropped'] += 1
            continue
        out.append(stripped)
    return "\n".join(out).rstrip("\n") + "\n"


NORM: collections.Counter = collections.Counter()


def main(sid: str, start: str, end: str, stem: str, part: str = "continuation") -> None:
    """Export records with start < timestamp < end (both bounds exclusive). `part` only changes the header wording."""
    src = next(PROJECTS.glob(f"*/{sid}.jsonl"))
    env_tool_ids, blocks, stats = set(), [], collections.Counter()
    first = last = None
    for raw in src.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        ts = ev.get("timestamp") or ""
        if not (start < ts < end) or ev.get("type") not in ("user", "assistant"):
            stats["skipped (harness / outside window)"] += 1
            continue
        content = (ev.get("message") or {}).get("content")
        items = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        out = []
        for x in items:
            if not isinstance(x, dict):
                continue
            t = x.get("type")
            if t == "text" and ev["type"] == "user":
                txt = clean_user_text(x.get("text", ""))
                if txt:
                    out.append(("🧑 User", txt))
                    stats["user prompts"] += 1
            elif t == "text":
                out.append(("🤖 Claude", x.get("text", "")))
                stats["assistant messages"] += 1
            elif t == "tool_use":
                if _ENV_FILE.search(json.dumps(x.get("input"))):
                    env_tool_ids.add(x.get("id"))
                out.append(("🤖 Claude", render_tool_use(x)))
                stats["tool calls"] += 1
            elif t == "tool_result":
                out.append(("⚙️ Tool", render_result(x, x.get("tool_use_id") in env_tool_ids)))
                stats["tool results"] += 1
            elif t == "image":
                HITS["embedded image removed"] += 1
                out.append(("🧑 User", "[image omitted]"))
            elif t == "thinking":
                stats["private reasoning blocks not exported"] += 1
        if out:
            stats["conversation records"] += 1
            first, last = first or ts, ts
            blocks.append((ts, out))
    scope = {"continuation": ("continuation", "the session after the existing export in this folder, up to the start of "
                                              "the export task itself"),
             "earlier": ("beginning to 9 November 2026", "the session from its start to the end of the existing export in "
                                                         "this folder, which this file replaces in redacted form")}[part]
    lines = [f"# Claude Code build session `{sid}` — {scope[0]}\n",
             f"Covers {first} to {last} (UTC): {scope[1]}. Rendered from the local transcript by "
             "`scripts/export_history_redacted.py`: prompts, "
             "replies, tool calls and truncated results only; secrets, account identifiers, personal data, local paths "
             "and images are redacted or removed (see the redaction report alongside).\n"]
    for ts, out in blocks:
        for who, text in out:
            lines.append(f"\n### {who} · {ts[:19]}Z\n\n{text}")
    md = normalise(redact("\n".join(lines)))
    (OUT / f"{stem}.md").write_text(md, encoding="utf-8", newline="\n")
    report = {"session": sid, "window_utc": {"after": start, "before": end}, "coverage_utc": {"first": first, "last": last},
              "counts": dict(stats), "redactions": dict(sorted(HITS.items())), "normalisation": dict(sorted(NORM.items())),
              "output": f"docs/ai-history/{stem}.md",
              "excluded": ["raw session records", "harness attachments (environment, account, file snapshots)",
                           "<system-reminder> and IDE-selection blocks", "model private reasoning (thinking)",
                           "results of tool calls that touched .env files", "embedded images and base64 payloads"]}
    (OUT / f"{stem}.redaction-report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("coverage_utc", "counts", "redactions", "normalisation")}, indent=1))
    print("wrote", f"docs/ai-history/{stem}.md", f"({len(md) // 1024} KB)", "and", f"docs/ai-history/{stem}.redaction-report.json")


if __name__ == "__main__":
    main(*sys.argv[1:6])
