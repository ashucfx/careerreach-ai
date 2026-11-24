from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ENV_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "service-account.json", "private.pem"}
FORBIDDEN_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def validate(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        parts = set(relative.parts)
        if path.suffix.lower() in {".md", ".markdown"} and relative.as_posix() != "README.md":
            issues.append(f"Markdown file is not permitted: {relative.as_posix()}")
        if path.name.lower() in FORBIDDEN_ENV_NAMES or path.name.lower().startswith(".env."):
            if path.name != ".env.example":
                issues.append(f"Environment or credential file is not permitted: {relative.as_posix()}")
        if parts & FORBIDDEN_PARTS:
            issues.append(f"Generated dependency or build path is not permitted: {relative.as_posix()}")
        if not path.is_file():
            issues.append(f"Tracked path is missing or not a file: {relative.as_posix()}")
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            issues.append(f"File exceeds 10 MiB: {relative.as_posix()}")
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            issues.append(f"Potential secret detected: {relative.as_posix()}")
    return issues


def main() -> int:
    issues = validate(tracked_paths())
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print("Repository hygiene checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
