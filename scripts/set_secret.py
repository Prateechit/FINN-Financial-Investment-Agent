"""Set one variable in backend/.env from a hidden prompt — the value is never echoed, printed or logged.

Run it in your own terminal (it needs a keyboard):
    backend\\.venv\\Scripts\\python.exe scripts\\set_secret.py RENDER_API_KEY

Only the line for that variable changes; every other line (and comment) is kept byte-for-byte. The file is rewritten
atomically (temp file in the same folder, then os.replace), so an interruption can't leave it half-written.
"""
import getpass
import os
import re
import sys
import tempfile
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / "backend" / ".env"
EXPECTED_PREFIX = {"RENDER_API_KEY": "rnd_", "GROQ_API_KEY": "gsk_"}


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[A-Z][A-Z0-9_]*", sys.argv[1]):
        sys.exit("usage: set_secret.py VARIABLE_NAME")
    name = sys.argv[1]
    if not sys.stdin.isatty():
        sys.exit("Run this in an interactive terminal so the value can be typed or pasted without being shown.")

    value = getpass.getpass(f"Paste {name} (input is hidden), then press Enter: ").strip().strip("'\"")
    if not value:
        sys.exit("Nothing entered — .env not changed.")
    if any(c.isspace() for c in value):
        sys.exit("The value contains spaces or line breaks — .env not changed. Copy the key again and retry.")
    prefix = EXPECTED_PREFIX.get(name)
    if prefix and not value.startswith(prefix):
        if input(f"Keys for {name} usually start with '{prefix}'. Save anyway? [y/N] ").strip().lower() != "y":
            sys.exit(".env not changed.")

    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    lines = text.splitlines()
    pattern = re.compile(rf"^\s*(?:export\s+)?{name}\s*=")
    found = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            if found:  # drop duplicate definitions so there is exactly one
                lines[i] = None
            else:
                lines[i], found = f"{name}={value}", True
    lines = [line for line in lines if line is not None]
    if not found:
        lines.append(f"{name}={value}")

    fd, tmp = tempfile.mkstemp(dir=ENV.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, ENV)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"{name} saved to backend/.env ({'updated existing entry' if found else 'added'}). The value was not displayed.")


if __name__ == "__main__":
    main()
