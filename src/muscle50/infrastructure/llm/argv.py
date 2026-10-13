"""The exact argv of each provider CLI. Tests pin these tuples; change them only with a new isolation check.

Isolation (live check 2026-10-12, docs/telegram-llm.md "Isolation"):

- Claude Code: `--tools ""` alone keeps the claude.ai connector tools (Gmail, Drive, ...); `--safe-mode`
  `--strict-mcp-config` `--disable-slash-commands` remove them, the slash commands, skills, hooks and
  auto-memory while the subscription login still works. `--bare` is never used (it skips the login).
  The only tool left is `StructuredOutput`, which is how `--json-schema` returns its answer.
- Claude Code with web search (v2.2, live check 2026-10-13): `--tools WebSearch` alone is refused in print mode
  (the model asks, the permission is denied), so the search variant also passes `--allowedTools WebSearch`.
  Nothing else changes: MCP servers stay 0 and `WebSearch` is the only tool besides `StructuredOutput`. The
  variant is used only for a request that asks for it; the argv above is byte-identical otherwise.
- Codex CLI: `--ignore-user-config --ignore-rules` skip `config.toml` (MCP servers, plugins) and the
  execpolicy rules; `web_search` and each feature below are disabled. Codex has no single "no tools"
  switch; the cwd holds only the photo and every answer is validated and confirmed by the user.

No user text, memory or persona ever goes into argv: the prompt is sent on stdin.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

CLAUDE_ISOLATION_ARGV: tuple[str, ...] = (
    "-p",
    "--tools",
    "",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
)

CLAUDE_WEB_ISOLATION_ARGV: tuple[str, ...] = (
    "-p",
    "--tools",
    "WebSearch",
    "--allowedTools",
    "WebSearch",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
)

CODEX_ISOLATION_ARGV: tuple[str, ...] = (
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "-s",
    "read-only",
    "--ignore-user-config",
    "--ignore-rules",
    "-c",
    'web_search="disabled"',
    "--disable",
    "shell_tool",
    "--disable",
    "unified_exec",
    "--disable",
    "code_mode_host",
    "--disable",
    "computer_use",
    "--disable",
    "browser_use",
    "--disable",
    "browser_use_external",
    "--disable",
    "in_app_browser",
    "--disable",
    "apps",
    "--disable",
    "plugins",
    "--disable",
    "multi_agent",
    "--disable",
    "image_generation",
    "--disable",
    "hooks",
    "--disable",
    "tool_suggest",
    "--disable",
    "skill_search",
    "--disable",
    "goals",
    "--disable",
    "sleep_tool",
    "--disable",
    "view_image",
)

CLAUDE_SYSTEM_PROMPT = (
    "You are the text-to-JSON interpreter of muscle50, a personal fitness log. You have no tools and must not "
    "try to use any. Read the single user message, follow the fixed rules written in it, and answer only with "
    "JSON that matches the given schema."
)
"""Fixed ASCII text; the persona and every user-dependent text are in the stdin prompt instead."""


CLAUDE_SYSTEM_PROMPT_WEB = (
    "You are the text-to-JSON interpreter of muscle50, a personal fitness log. You have exactly one tool, "
    "WebSearch, and must use it only as the fixed rules written in the user message allow; do not try to use any "
    "other tool. Read the single user message, follow the fixed rules written in it, and answer only with JSON "
    "that matches the given schema."
)
"""Used instead of `CLAUDE_SYSTEM_PROMPT` only when the search tool is offered."""


def claude_argv(executable: str, model: str | None, schema: object, *, web_search: bool = False) -> tuple[str, ...]:
    return (
        executable,
        *(CLAUDE_WEB_ISOLATION_ARGV if web_search else CLAUDE_ISOLATION_ARGV),
        *(("--model", model) if model is not None else ()),
        "--system-prompt",
        CLAUDE_SYSTEM_PROMPT_WEB if web_search else CLAUDE_SYSTEM_PROMPT,
        "--json-schema",
        json.dumps(schema, separators=(",", ":"), ensure_ascii=True),
    )


def codex_argv(
    executable: str,
    model: str | None,
    *,
    schema_path: Path,
    output_path: Path,
    work_dir: Path,
    photo_path: Path | None,
) -> tuple[str, ...]:
    # `-` (prompt from stdin) comes before `-i`: `-i` takes several values and would swallow it.
    return (
        executable,
        *CODEX_ISOLATION_ARGV,
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-C",
        str(work_dir),
        *(("-m", model) if model is not None else ()),
        "-",
        *(("-i", str(photo_path)) if photo_path is not None else ()),
    )


def claude_stdin(prompt: str, photo: bytes | None) -> bytes:
    """One stream-json user message: the prompt as a text block, then the photo as a base64 image block."""
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    if photo is not None:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type(photo),
                    "data": base64.b64encode(photo).decode("ascii"),
                },
            }
        )
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return (json.dumps(message, ensure_ascii=True) + "\n").encode("ascii")


def image_media_type(photo: bytes) -> str:
    """From the file's magic bytes; Telegram photos are JPEG, which is also the default."""
    if photo.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if photo[:4] == b"RIFF" and photo[8:12] == b"WEBP":
        return "image/webp"
    if photo.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "image/jpeg"


def image_suffix(photo: bytes) -> str:
    return "." + image_media_type(photo).removeprefix("image/").replace("jpeg", "jpg")
