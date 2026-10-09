"""Fail if the public repo contains personal data (PROMPT.md §10).

Scans every file git would commit (tracked + untracked-not-ignored) for:
  1. email addresses other than the fictional sample person's and no-reply addresses;
  2. phone-number shapes, other than the sample person's invented number;
  3. an exact denylist of the owner's contact strings.

The denylist itself must never be in this repo. It comes from the RT_DENYLIST environment
variable (newline- or comma-separated; in CI, the PRIVACY_DENYLIST secret) or, locally,
from `--data-dir PATH`, which reads `owner.contact_strings` from the private config.yml.
Matches of the denylist are reported by file and line only, never echoed.

    python scripts/privacy_scan.py [--data-dir ../resume-data]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "users.noreply.github.com",
                         "anthropic.com")
SAMPLE_PHONE_DIGITS = "905550102030"
EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
PHONE_RE = re.compile(r"\+\d{1,3}[\s.-]?\(?\d{2,4}\)?(?:[\s.-]?\d{2,4}){2,4}")
SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".zip"}


def repo_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    return [root / p for p in out.split("\0") if p]


def denylist(data_dir: str | None) -> list[str]:
    items: list[str] = []
    env = os.environ.get("RT_DENYLIST", "")
    items += [s.strip() for s in re.split(r"[\n,]", env) if s.strip()]
    if data_dir:
        import yaml

        cfg = yaml.safe_load((Path(data_dir) / "config.yml").read_text(encoding="utf-8"))
        owner = cfg.get("owner", {})
        names = {n.lower() for n in owner.get("names", [])}
        contacts = owner.get("contact_strings", [])
        github_users = {m.group(1).lower() for s in contacts
                        if (m := re.search(r"github\.com/([\w-]+)", s, re.I))}
        for s in contacts:
            # The GitHub account is public by design: the repo lives under it and the docs
            # reference it. Names are public too. Everything else is private.
            low = s.lower()
            if ("github" in low or low in github_users or low in names
                    or any(low in n for n in names)):
                continue
            if len(re.sub(r"\W", "", s)) >= 5:  # too-short strings would match everywhere
                items.append(s)
    return sorted(set(items), key=len, reverse=True)


def scan(root: Path, deny: list[str]) -> list[str]:
    problems: list[str] = []
    deny_folded = [(d, d.casefold()) for d in deny]
    deny_digits = [re.sub(r"\D", "", d) for d in deny if len(re.sub(r"\D", "", d)) >= 9]
    for path in repo_files(root):
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            for m in EMAIL_RE.finditer(line):
                domain = m.group(1).lower()
                if not domain.endswith(ALLOWED_EMAIL_DOMAINS):
                    problems.append(f"{rel}:{n}: email address ({domain})")
            for m in PHONE_RE.finditer(line):
                digits = re.sub(r"\D", "", m.group(0))
                if len(digits) >= 10 and digits != SAMPLE_PHONE_DIGITS:
                    problems.append(f"{rel}:{n}: phone-like number")
            low = line.casefold()
            for _, d in deny_folded:
                if d in low:
                    problems.append(f"{rel}:{n}: denylisted contact string")
            line_digits = re.sub(r"\D", "", line)
            for d in deny_digits:
                if d in line_digits:
                    problems.append(f"{rel}:{n}: denylisted phone number")
    return sorted(set(problems))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", help="private data repo (reads owner.contact_strings)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    deny = denylist(a.data_dir)
    problems = scan(Path(a.root), deny)
    print(f"privacy scan: {len(deny)} denylisted string(s), {len(problems)} problem(s)")
    for p in problems:
        print(f"  {p}")
    if not deny:
        print("  note: no denylist given (set RT_DENYLIST or --data-dir); pattern checks only")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
