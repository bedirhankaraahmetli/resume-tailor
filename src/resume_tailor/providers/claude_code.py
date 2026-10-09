"""Claude Code headless (`claude -p`): fallback 1, billed to the Pro subscription.

Isolation matters more here than anywhere else. Headless Claude Code would otherwise read
CLAUDE.md files and settings from its working directory and every parent, run project
hooks, and start MCP servers. So it runs in an empty temporary directory, with no tools,
no setting sources, no MCP config, our own system prompt, and the payload on stdin.

`--bare` would be simpler but it ignores CLAUDE_CODE_OAUTH_TOKEN (the CI credential), so
it cannot be used with a subscription.

Cost is recorded as 0: the call counts against Pro usage limits, not API credits.
ANTHROPIC_API_KEY is removed from the child environment, because Claude Code prefers an
API key over the subscription token and would silently bill the prepaid credits.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import Config
from .base import LLMCall, LLMResponse, ProviderError, Usage, strict_schema


def find_claude(configured: str | None) -> str | None:
    if configured:
        return configured if Path(configured).exists() else None
    found = shutil.which("claude")
    if found:
        return found
    # VS Code ships its own binary and does not put it on PATH.
    pattern = str(Path.home() / ".vscode/extensions/anthropic.claude-code-*/resources/"
                  "native-binary/claude*")
    hits = sorted(h for h in glob.glob(pattern) if not h.endswith(".md"))
    return hits[-1] if hits else None


class ClaudeCodeProvider:
    name = "claude-code"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.cfg = config.providers.claude_code

    def available(self) -> bool:
        return find_claude(self.cfg.executable) is not None

    def complete(self, call: LLMCall) -> LLMResponse:
        exe = find_claude(self.cfg.executable)
        if exe is None:
            raise ProviderError("unavailable", "Claude Code CLI not found")
        model = call.model_override or self.cfg.model
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
        with tempfile.TemporaryDirectory(prefix="rt-cc-") as tmp:
            sys_file = Path(tmp) / "system.md"
            sys_file.write_text(call.system, encoding="utf-8")
            cmd = [
                exe, "-p",
                "--output-format", "json",
                "--json-schema", json.dumps(strict_schema(call.schema)),
                "--model", model,
                "--system-prompt-file", str(sys_file),
                "--tools", "",
                "--strict-mcp-config",
                "--setting-sources", "",
                "--no-session-persistence",
                "--max-turns", "3",
            ]
            work = Path(tmp) / "work"
            work.mkdir()
            try:
                proc = subprocess.run(
                    cmd, input=call.user, cwd=work, env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.cfg.timeout_s,
                )
            except subprocess.TimeoutExpired as e:
                raise ProviderError("timeout", "Claude Code timed out") from e
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise ProviderError("server", f"Claude Code failed: {tail[0][:200]}") from e
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
            cache_write_tokens=int(u.get("cache_creation_input_tokens") or 0),
            cache_read_tokens=int(u.get("cache_read_input_tokens") or 0),
        )
        if data.get("is_error") or data.get("subtype") != "success":
            msg = ("; ".join(data.get("errors") or [])
                   or str(data.get("result") or data.get("subtype")))
            low = msg.lower()
            kind = ("rate_limit" if "limit" in low else "auth" if "login" in low or "auth" in low
                    else "invalid" if "structured" in low else "server")
            raise ProviderError(kind, f"Claude Code: {msg[:300]}")  # type: ignore[arg-type]
        structured = data.get("structured_output")
        if structured is None:
            # The docs say success without structured_output is still a failure.
            raise ProviderError("invalid", "Claude Code returned no structured output",
                                LLMResponse(str(data.get("result") or ""), usage, self.name,
                                            model, 0.0))
        return LLMResponse(json.dumps(structured, ensure_ascii=False), usage, self.name, model, 0.0)
