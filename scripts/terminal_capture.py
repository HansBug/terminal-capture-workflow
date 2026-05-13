#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOTNAME = ".terminal-capture-output"
DEFAULT_END_HOLD_MS = 2000
INIT_VALID_ENGINES = ("ttyd", "vhs", "all")
# Default regex matched against the rendered terminal text to detect that
# a shell prompt has returned after a command finishes. Covers bash / zsh
# / sh (`$`), root / `#`, csh / `%`, starship / fish (`❯`, `▶`), and the
# generic `>` that VHS's default Ubuntu theme uses out of the box.
#
# Multiline semantics are passed as a FLAG by each engine rather than
# baked into the pattern as `(?m)`, because JavaScript's RegExp does not
# accept the `(?m)` inline-flag syntax (Python and Go do, but parity is
# easier to enforce one way than three). Python callers must pass
# `re.MULTILINE`; the ttyd Playwright renderer passes the `"m"` flag
# to `new RegExp(...)`; for VHS the rendered viewport snapshot ends at
# the prompt anyway, so Go regexp's default end-of-string `$` happens
# to coincide with end-of-line at the matching point.
#
# Known limitations (use an explicit `wait_for_prompt: "<regex>"` to
# work around any of these):
#   * Bash PS2 continuation (multi-line commands inside `for / while /
#     do … done`, unclosed quotes, heredoc bodies). PS2's default form
#     is `> `, so the default regex fires on the continuation prompt
#     before the *outer* command actually returns. Scenarios that drive
#     multi-line bash should pass a regex without `>` in the class —
#     e.g. `"wait_for_prompt": "[\\$#%▶❯]\\s*$"`.
#   * Output content that genuinely ends in a class char (`grep ... >`,
#     `cat`-ed Markdown with `>` quotes) right before the prompt would
#     have appeared.
#   * ASCII-only or missing-glyph terminals where `▶` / `❯` render as
#     `?` placeholders — the default class won't see the prompt char.
#     Choose an explicit ASCII-only prompt or `wait_for_text` instead.
DEFAULT_PROMPT_REGEX = r"[\$#%▶❯>]\s*$"
# Scenario names become file stems on disk and the `name` field VHS uses
# for tape / output paths. Restrict to characters that are safe on every
# filesystem and shell we target: ASCII letters and digits to start,
# followed by letters, digits, `_`, or `-`. No leading dot (hidden file
# trap), no `/` (path injection), no whitespace.
INIT_SCENARIO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
VHS_KEY_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "esc": "Ctrl+[",
    "escape": "Ctrl+[",
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "pgup": "PageUp",
    "pageup": "PageUp",
    "pgdn": "PageDown",
    "pgdown": "PageDown",
    "pagedown": "PageDown",
    "del": "Delete",
    "delete": "Delete",
    "ins": "Insert",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "backspace": "Backspace",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "spacebar": "Space",
    "space": "Space",
}
VHS_SPECIAL_KEYS = {
    "Enter",
    "Tab",
    "Space",
    "Backspace",
    "Delete",
    "Insert",
    "Home",
    "End",
    "PageUp",
    "PageDown",
    "Up",
    "Down",
    "Left",
    "Right",
}
BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


def load_scenario(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def format_duration(ms: int) -> str:
    if ms % 1000 == 0:
        return f"{ms // 1000}s"
    return f"{ms}ms"


def _command_wrap_breakpoints(text: str) -> list[int]:
    """Return safe wrap breakpoints outside quoted shell regions."""
    points: list[int] = []
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char.isspace() and not in_single and not in_double:
            points.append(index)

    return points


def wrap_shell_command_text(
    text: str,
    wrap_at_columns: int,
    continuation_indent: int = 2,
    prompt_columns: int = 0,
    continuation_prompt_columns: int = 0,
) -> str:
    """
    Wrap one shell command into backslash-continued lines for display stability.

    The wrapped text stays shell-equivalent by inserting ``\\`` before each
    synthetic newline. Breaks prefer whitespace outside quoted regions.

    If a forced break would land on one or more literal backslashes, those
    backslashes are rolled back into the head of the next chunk so the
    rendered line never ends in ``\\ \\`` (which a shell parses as
    escaped-space plus literal backslash, not as line continuation).

    Pathological fallback (silent, by design): if rolling back the trailing
    backslashes empties the chunk entirely — i.e., the input is dominated by
    literal ``\\`` characters with no break-friendly content before them —
    the function returns the original text unchanged. Wrapping is silently
    disabled rather than producing a broken continuation line. Callers that
    care about whether wrapping happened can compare the return value to
    the input.

    :param text: Raw shell command text.
    :type text: str
    :param wrap_at_columns: Maximum display width before wrapping.
    :type wrap_at_columns: int
    :param continuation_indent: Number of leading spaces on continuation lines.
    :type continuation_indent: int, optional
    :param prompt_columns: Visible prompt width on the first command line.
    :type prompt_columns: int, optional
    :param continuation_prompt_columns: Visible prompt width on wrapped
        continuation lines.
    :type continuation_prompt_columns: int, optional
    :return: Wrapped shell command text, or the input unchanged when no
        safe wrap is possible.
    :rtype: str
    """
    wrap_at_columns = max(20, int(wrap_at_columns))
    continuation_indent = max(0, int(continuation_indent))
    prompt_columns = max(0, int(prompt_columns))
    continuation_prompt_columns = max(0, int(continuation_prompt_columns))
    indent = " " * continuation_indent
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if "\n" in normalized:
        return normalized

    safe_points = set(_command_wrap_breakpoints(normalized))
    lines: list[str] = []
    start = 0
    current_limit = max(12, wrap_at_columns - prompt_columns - 2)

    while len(normalized) - start > current_limit:
        end = start + current_limit
        break_index = -1

        for index in range(end, start, -1):
            if index - 1 in safe_points:
                break_index = index - 1
                break

        if break_index < start:
            break_index = end
            while break_index > start and normalized[break_index - 1].isspace():
                break_index -= 1
            if break_index <= start:
                return normalized

        chunk = normalized[start:break_index].rstrip()
        if not chunk:
            return normalized

        while chunk.endswith("\\"):
            chunk = chunk[:-1]
            break_index -= 1
        if not chunk:
            return normalized

        lines.append(f"{chunk} \\")
        start = break_index
        while start < len(normalized) and normalized[start].isspace():
            start += 1
        current_limit = max(
            12,
            wrap_at_columns
            - continuation_prompt_columns
            - continuation_indent
            - 2,
        )

    lines.append(f"{indent if lines else ''}{normalized[start:]}")
    if len(lines) > 1:
        return "\n".join([lines[0], *[f"{indent}{line}" for line in lines[1:]]])
    return lines[0]


def escape_vhs_text(text: str) -> str:
    return (
        text.replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )


def escape_vhs_regex(pattern: str) -> str:
    return pattern.replace("/", "\\/")


def resolve_wait_prompt_pattern(value: Any) -> str | None:
    """Translate a ``wait_for_prompt`` field value to a regex string or ``None``.

    Accepted shapes:

    - ``True`` → :data:`DEFAULT_PROMPT_REGEX`
    - ``str`` whose :meth:`str.strip` is non-empty → used verbatim as a regex
    - ``False`` / ``None`` / unset → ``None`` (no prompt wait)

    Any other shape raises :class:`ValueError` so typos surface
    immediately rather than silently no-op. In particular this includes:

    - blank-only strings (``""``, ``"   "``, ``"\\t"``) — almost certainly
      a typo, never a useful regex. If you really want to match
      whitespace, write ``"\\\\s+"`` or similar.
    - non-bool / non-string values (numbers, lists, dicts, …).
    """
    if value is True:
        return DEFAULT_PROMPT_REGEX
    if value is False or value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(
                "wait_for_prompt must be a bool or a NON-EMPTY string regex; "
                f"got blank string {value!r}"
            )
        return value
    raise ValueError(
        "wait_for_prompt must be a bool or a string regex, got "
        f"{type(value).__name__}: {value!r}"
    )


def resolve_wait_pattern(step: dict[str, Any], engine: str) -> str | None:
    if "pattern_by_engine" in step:
        return step["pattern_by_engine"].get(engine) or step.get("pattern")
    if "wait_for_text_by_engine" in step:
        return step["wait_for_text_by_engine"].get(engine) or step.get("wait_for_text")
    return step.get("pattern") or step.get("wait_for_text")


def resolve_command_text(step: dict[str, Any]) -> str:
    """
    Return the rendered command text for one scenario step.

    :param step: Scenario step dictionary.
    :type step: dict[str, typing.Any]
    :return: Command text to type into the terminal.
    :rtype: str
    """
    text = step["text"]
    wrap_at_columns = step.get("wrap_at_columns")
    if wrap_at_columns is not None:
        return wrap_shell_command_text(
            text,
            wrap_at_columns=wrap_at_columns,
            continuation_indent=step.get("wrap_indent", 2),
            prompt_columns=step.get("prompt_columns", 0),
            continuation_prompt_columns=step.get(
                "continuation_prompt_columns", 0
            ),
        )
    return text


def ensure_input_event_fields(event: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if field not in event]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Input event is missing required field(s): {missing_text}")


def parse_positive_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer.") from error
    return max(0, parsed)


def parse_positive_seconds_to_ms(value: Any, label: str) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number of seconds.") from error
    return max(0, int(round(parsed * 1000)))


def resolve_vhs_outputs(cfg: dict[str, Any]) -> list[str]:
    outputs = cfg.get("outputs", ["mp4"])
    return [str(ext).lower() for ext in outputs]


def has_motion_outputs(cfg: dict[str, Any]) -> bool:
    return any(ext in {"gif", "mp4", "webm"} for ext in resolve_vhs_outputs(cfg))


def resolve_end_hold_ms(cfg: dict[str, Any]) -> int:
    if "endHoldMs" in cfg:
        return parse_positive_int(cfg["endHoldMs"], "vhs.endHoldMs")
    if "endHoldSeconds" in cfg:
        return parse_positive_seconds_to_ms(cfg["endHoldSeconds"], "vhs.endHoldSeconds")
    if has_motion_outputs(cfg):
        return DEFAULT_END_HOLD_MS
    return 0


def build_vhs_type_command(text: str, delay_ms: int | None = None) -> str:
    delay_part = f"@{format_duration(delay_ms)}" if delay_ms else ""
    return f'Type{delay_part} "{escape_vhs_text(text)}"'


def build_vhs_text_commands(text: str, delay_ms: int | None = None) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("\n")
    commands: list[str] = []

    for index, part in enumerate(parts):
        if part:
            commands.append(build_vhs_type_command(part, delay_ms))
        if index != len(parts) - 1:
            commands.append("Enter")

    return commands or [build_vhs_type_command("", delay_ms)]


def normalize_vhs_key_part(part: str) -> str:
    trimmed = part.strip()
    if not trimmed:
        raise ValueError("VHS key commands cannot contain empty segments.")
    if len(trimmed) == 1:
        return trimmed
    return VHS_KEY_ALIASES.get(trimmed.casefold(), trimmed)


def normalize_vhs_key(key: str) -> str:
    trimmed = key.strip()
    if not trimmed:
        raise ValueError("VHS key commands cannot be empty.")

    parts = [part.strip() for part in trimmed.split("+")]
    if len(parts) == 1:
        return normalize_vhs_key_part(parts[0])

    normalized_parts = [normalize_vhs_key_part(part) for part in parts]
    modifiers = normalized_parts[:-1]
    base = normalized_parts[-1]

    if base == "Ctrl+[":
        if modifiers:
            raise ValueError(
                f"Unsupported VHS key combo `{key}`. Prefer ttyd for this chord or use `raw_vhs` for explicit VHS commands."
            )
        return base

    if len(base) == 1:
        return "+".join([*modifiers, base])

    if base in VHS_SPECIAL_KEYS and len(modifiers) <= 1:
        return "+".join([*modifiers, base])

    raise ValueError(
        f"Unsupported VHS key combo `{key}`. Prefer ttyd for this chord or use `raw_vhs` for explicit VHS commands."
    )


def build_vhs_press_commands(key: str, repeat: int = 1, delay_ms: int | None = None) -> list[str]:
    normalized = normalize_vhs_key(key)
    repeat = max(1, repeat)
    delay_part = f"@{format_duration(delay_ms)}" if delay_ms else ""

    if len(normalized) == 1 and normalized.isprintable():
        return [build_vhs_type_command(normalized * repeat, delay_ms)]

    if normalized in VHS_SPECIAL_KEYS or normalized.startswith("Ctrl+") or normalized.startswith("Alt+") or normalized.startswith("Shift+"):
        repeat_part = f" {repeat}" if repeat != 1 else ""
        return [f"{normalized}{delay_part}{repeat_part}"]

    raise ValueError(f"Unsupported VHS key `{key}`. Prefer ttyd for this chord or use `raw_vhs` for explicit VHS commands.")


def append_vhs_input_event(lines: list[str], event: dict[str, Any]) -> None:
    kind = event.get("kind")

    if kind == "sleep":
        ensure_input_event_fields(event, "ms")
        lines.append(f'Sleep {format_duration(parse_positive_int(event["ms"], "input sleep ms"))}')
        return

    if kind == "text":
        ensure_input_event_fields(event, "text")
        delay_ms = event.get("delay_ms")
        lines.extend(
            build_vhs_text_commands(
                event["text"],
                parse_positive_int(delay_ms, "input text delay") if delay_ms is not None else None,
            )
        )
        return

    if kind == "paste":
        ensure_input_event_fields(event, "text")
        delay_ms = event.get("delay_ms")
        lines.extend(
            build_vhs_text_commands(
                event["text"],
                parse_positive_int(delay_ms, "input paste delay") if delay_ms is not None else 1,
            )
        )
        return

    if kind == "press":
        ensure_input_event_fields(event, "key")
        repeat = parse_positive_int(event.get("repeat", 1), "input press repeat") or 1
        delay_ms = event.get("delay_ms")
        lines.extend(
            build_vhs_press_commands(
                event["key"],
                repeat=repeat,
                delay_ms=parse_positive_int(delay_ms, "input press delay") if delay_ms is not None else None,
            )
        )
        return

    raise ValueError(f"Unsupported input event kind: {kind}")


def run_checked(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def find_on_path(name: str) -> str | None:
    return shutil.which(name)


def have_pillow() -> bool:
    return importlib.util.find_spec("PIL") is not None


def detect_playwright_package() -> bool:
    return (SKILL_ROOT / "node_modules" / "playwright" / "package.json").exists()


def detect_system_browser() -> str | None:
    for candidate in BROWSER_CANDIDATES:
        resolved = find_on_path(candidate)
        if resolved:
            return resolved
    return None


def detect_playwright_browser() -> str | None:
    if not detect_playwright_package():
        return None

    script = """
const fs = require('fs');
try {
  const { chromium } = require('playwright');
  const executable = chromium.executablePath();
  if (executable && fs.existsSync(executable)) {
    process.stdout.write(executable);
  }
} catch (error) {}
"""
    try:
        result = subprocess.run(
            ["node", "-e", script],
            cwd=SKILL_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    browser_path = result.stdout.strip()
    return browser_path or None


def detect_environment() -> dict[str, Any]:
    tools = {
        "python3": find_on_path("python3") or sys.executable,
        "node": find_on_path("node"),
        "npm": find_on_path("npm"),
        "ttyd": find_on_path("ttyd"),
        "vhs": find_on_path("vhs"),
        "ffmpeg": find_on_path("ffmpeg"),
        "ffprobe": find_on_path("ffprobe"),
        "less": find_on_path("less"),
        "apt": find_on_path("apt") or find_on_path("apt-get"),
    }
    extras = {
        "python_pillow": have_pillow(),
        "playwright_package": detect_playwright_package(),
    }
    extras["system_browser"] = detect_system_browser()
    extras["playwright_browser"] = detect_playwright_browser()

    capabilities = {
        "ttyd_screenshots": bool(
            tools["ttyd"]
            and tools["node"]
            and tools["npm"]
            and extras["playwright_package"]
            and (extras["system_browser"] or extras["playwright_browser"])
        ),
        "vhs_media": bool(tools["vhs"] and tools["ffmpeg"]),
        "vhs_stills": bool(tools["vhs"] and tools["ffmpeg"]),
        "frame_extraction": bool(tools["ffmpeg"]),
        "media_probe": bool(tools["ffprobe"]),
        "autocrop_pngs": extras["python_pillow"],
    }

    return {
        "system": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "skill_root": str(SKILL_ROOT),
        },
        "tools": tools,
        "extras": extras,
        "capabilities": capabilities,
        "install_commands": build_install_commands(tools, extras),
    }


def build_install_commands(tools: dict[str, str | None], extras: dict[str, Any]) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}

    apt_packages: list[str] = []
    if not tools["ttyd"]:
        apt_packages.append("ttyd")
    if not tools["ffmpeg"]:
        apt_packages.append("ffmpeg")
    if not tools["less"]:
        apt_packages.append("less")
    if not tools["node"]:
        apt_packages.append("nodejs")
    if not tools["npm"]:
        apt_packages.append("npm")
    if not extras["python_pillow"]:
        apt_packages.append("python3-pil")

    if tools["apt"] and apt_packages:
        commands["apt"] = [
            "sudo apt update",
            f"sudo apt install -y {' '.join(sorted(dict.fromkeys(apt_packages)))}",
        ]

    if not tools["vhs"]:
        commands["vhs"] = [
            "sudo mkdir -p /etc/apt/keyrings",
            "curl -fsSL https://repo.charm.sh/apt/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg",
            "echo \"deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *\" | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null",
            "sudo apt update",
            "sudo apt install -y vhs",
        ]

    if not extras["playwright_package"]:
        commands["playwright_package"] = [
            f"cd {shlex_quote(str(SKILL_ROOT))}",
            "npm install",
        ]

    if not extras["system_browser"] and not extras["playwright_browser"]:
        commands["playwright_browser"] = [
            f"cd {shlex_quote(str(SKILL_ROOT))}",
            "npx playwright install chromium",
        ]

    return commands


def shlex_quote(text: str) -> str:
    return shlex.quote(text)


def print_check_report(environment: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(environment, indent=2))
        return

    print("Environment report for terminal-capture-workflow")
    print(f"Skill root: {environment['system']['skill_root']}")
    print(f"Platform: {environment['system']['platform']}")
    print(f"Python: {environment['system']['python']}")
    print("")
    print("Capabilities:")
    for key, value in environment["capabilities"].items():
        status = "ready" if value else "blocked"
        print(f"  - {key}: {status}")
    print("")
    print("Detected tools:")
    for key, value in environment["tools"].items():
        print(f"  - {key}: {value or 'missing'}")
    print("")
    print("Detected extras:")
    for key, value in environment["extras"].items():
        print(f"  - {key}: {value or 'missing'}")

    if environment["install_commands"]:
        print("")
        print("Suggested install commands:")
        for label, commands in environment["install_commands"].items():
            print(f"  [{label}]")
            for command in commands:
                print(f"    {command}")


def normalize_scenario_path(raw_path: str) -> Path:
    scenario_path = Path(raw_path)
    if not scenario_path.is_absolute():
        scenario_path = (Path.cwd() / scenario_path).resolve()
    return scenario_path


def default_output_root(cwd: Path) -> Path:
    return cwd / DEFAULT_OUTPUT_ROOTNAME


def parse_fraction(text: str | None) -> float | None:
    if not text or text == "0/0":
        return None
    return float(Fraction(text))


def probe_media(path: Path) -> dict[str, Any]:
    if not find_on_path("ffprobe"):
        raise RuntimeError("ffprobe is required for media probing. Install ffmpeg first.")

    result = run_checked(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        path.parent,
    )
    data = json.loads(result.stdout)
    video_stream = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
    format_info = data.get("format", {})
    duration_raw = format_info.get("duration")
    duration_seconds = float(duration_raw) if duration_raw else None
    fps = parse_fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))

    return {
        "path": str(path),
        "duration_seconds": duration_seconds,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "fps": fps,
        "codec": video_stream.get("codec_name"),
    }


def suggested_review_times(duration_seconds: float | None) -> list[str]:
    if not duration_seconds or duration_seconds <= 0.15:
        return []

    raw_points = [duration_seconds * ratio for ratio in (0.2, 0.5, 0.8)]
    clipped = [point for point in raw_points if point < duration_seconds]
    unique_points = sorted({max(0.05, round(point, 2)) for point in clipped})
    return [f"{point:g}" for point in unique_points]


def scenario_cwd(scenario_path: Path, scenario: dict[str, Any], cli_cwd: str | None) -> Path:
    if cli_cwd:
        return Path(cli_cwd).resolve()
    if scenario.get("cwd"):
        return Path(scenario["cwd"]).resolve()
    return scenario_path.parent.resolve()


def autocrop_png(path: Path, padding: int) -> None:
    if not have_pillow():
        return

    from PIL import Image, ImageChops

    image = Image.open(path)
    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if not bbox:
        return

    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    image.crop((left, top, right, bottom)).save(path)


def postprocess_screenshots(scenario: dict[str, Any], out_dir: Path) -> None:
    screenshot_cfg = scenario.get("screenshots", {})
    if not screenshot_cfg.get("autocrop", True):
        return
    if not have_pillow():
        return

    padding = screenshot_cfg.get("padding", 18)
    for png_path in sorted(out_dir.glob("*.png")):
        autocrop_png(png_path, padding)


def build_vhs_tape(scenario: dict[str, Any], out_dir: Path) -> str:
    cfg = scenario.get("vhs", {})
    scenario_name = scenario["name"]
    lines: list[str] = []
    screenshot_settle_ms = cfg.get("screenshotSettleMs", 120)
    end_hold_ms = resolve_end_hold_ms(cfg)

    for ext in resolve_vhs_outputs(cfg):
        lines.append(f'Output "{(out_dir / f"{scenario_name}.{ext}").as_posix()}"')

    requires = list(dict.fromkeys(["bash", *scenario.get("requires", [])]))
    lines.extend(
        [
            "",
            *[f"Require {program}" for program in requires],
            'Set Shell "bash"',
            f'Set FontSize {cfg.get("fontSize", 22)}',
            f'Set Width {cfg.get("width", 1280)}',
            f'Set Height {cfg.get("height", 760)}',
            f'Set Padding {cfg.get("padding", 24)}',
            f'Set WindowBar {cfg.get("windowBar", "Colorful")}',
            f'Set BorderRadius {cfg.get("borderRadius", 10)}',
            f'Set Theme "{cfg.get("theme", "Ubuntu")}"',
            f'Set TypingSpeed {cfg.get("typingSpeed", "35ms")}',
            f'Set Framerate {cfg.get("framerate", 30)}',
        ]
    )

    if "playbackSpeed" in cfg:
        lines.append(f'Set PlaybackSpeed {cfg["playbackSpeed"]}')

    if cfg.get("waitTimeout"):
        lines.append(f'Set WaitTimeout {format_duration(cfg["waitTimeout"])}')

    lines.append("")

    for step in scenario.get("steps", []):
        action = step["action"]

        if action == "sleep":
            lines.append(f'Sleep {format_duration(step["ms"])}')
        elif action == "type":
            delay_ms = step.get("delay_ms")
            lines.extend(
                build_vhs_text_commands(
                    step["text"],
                    parse_positive_int(delay_ms, "type delay") if delay_ms is not None else None,
                )
            )
        elif action == "paste":
            delay_ms = step.get("delay_ms")
            lines.extend(
                build_vhs_text_commands(
                    step["text"],
                    parse_positive_int(delay_ms, "paste delay") if delay_ms is not None else 1,
                )
            )
        elif action == "press":
            delay_ms = step.get("delay_ms")
            lines.extend(
                build_vhs_press_commands(
                    step["key"],
                    repeat=parse_positive_int(step.get("repeat", 1), "press repeat") or 1,
                    delay_ms=parse_positive_int(delay_ms, "press delay") if delay_ms is not None else None,
                )
            )
        elif action == "input":
            for event in step.get("events", []):
                append_vhs_input_event(lines, event)
        elif action == "wait_for_text":
            timeout = step.get("timeout_ms")
            timeout_part = f'@{format_duration(timeout)}' if timeout else ""
            pattern = resolve_wait_pattern(step, "vhs")
            lines.append(f'Wait+Screen{timeout_part} /{escape_vhs_regex(pattern)}/')
        elif action == "wait_for_prompt":
            prompt_pattern = resolve_wait_prompt_pattern(step.get("prompt"))
            if not prompt_pattern:
                raise ValueError(
                    "wait_for_prompt action requires `prompt` (true or a non-empty regex string)."
                )
            timeout = step.get("timeout_ms")
            timeout_part = f'@{format_duration(timeout)}' if timeout else ""
            lines.append(f'Wait+Screen{timeout_part} /{escape_vhs_regex(prompt_pattern)}/')
        elif action == "screenshot":
            screenshot_path = out_dir / f'{step["name"]}.png'
            lines.append(f'Screenshot "{screenshot_path.as_posix()}"')
            lines.append(f"Sleep {format_duration(screenshot_settle_ms)}")
        elif action == "command":
            if step.get("clear_before"):
                lines.append("Ctrl+L")
                lines.append("Sleep 120ms")
            command_text = resolve_command_text(step)
            lines.extend(
                build_vhs_text_commands(
                    command_text,
                    parse_positive_int(step.get("delay_ms", 0), "command delay") or None,
                )
            )
            if step.get("typed_shot"):
                typed_path = out_dir / f'{step["typed_shot"]}.png'
                lines.append(f'Screenshot "{typed_path.as_posix()}"')
                lines.append(f"Sleep {format_duration(screenshot_settle_ms)}")
            lines.append("Enter")
            wait_pattern = resolve_wait_pattern(step, "vhs")
            prompt_pattern = resolve_wait_prompt_pattern(step.get("wait_for_prompt"))
            timeout = step.get("timeout_ms")
            timeout_part = f'@{format_duration(timeout)}' if timeout else ""
            if wait_pattern:
                lines.append(f'Wait+Screen{timeout_part} /{escape_vhs_regex(wait_pattern)}/')
            if prompt_pattern:
                # wait_for_text fires on the first occurrence of a summary
                # line; wait_for_prompt fires once the shell has actually
                # returned to a prompt. Emitting the prompt wait *after*
                # the text wait gives the "summary visible AND command
                # finished" guarantee that field-notes recommends.
                lines.append(f'Wait+Screen{timeout_part} /{escape_vhs_regex(prompt_pattern)}/')
            if not wait_pattern and not prompt_pattern:
                lines.append(f'Sleep {format_duration(step.get("result_delay_ms", 900))}')
            if step.get("result_shot"):
                result_path = out_dir / f'{step["result_shot"]}.png'
                lines.append(f'Screenshot "{result_path.as_posix()}"')
                lines.append(f"Sleep {format_duration(screenshot_settle_ms)}")
        elif action == "hide":
            lines.append("Hide")
        elif action == "show":
            lines.append("Show")
        elif action == "raw_vhs":
            raw_lines = step.get("lines") or ([step["line"]] if "line" in step else [])
            if not raw_lines:
                raise ValueError("raw_vhs requires `line` or `lines`.")
            lines.extend(raw_lines)
        else:
            raise ValueError(f"Unsupported VHS action: {action}")

    if end_hold_ms:
        lines.append(f"Sleep {format_duration(end_hold_ms)}")

    lines.append("")
    return "\n".join(lines)


def ensure_engine_ready(engine: str, environment: dict[str, Any]) -> None:
    capabilities = environment["capabilities"]
    install_commands = environment["install_commands"]
    missing_reason = None

    if engine == "ttyd" and not capabilities["ttyd_screenshots"]:
        missing_reason = "ttyd screenshot rendering is blocked"
    elif engine == "vhs" and not capabilities["vhs_media"]:
        missing_reason = "VHS rendering is blocked"
    elif engine == "all":
        blocked = []
        if not capabilities["ttyd_screenshots"]:
            blocked.append("ttyd")
        if not capabilities["vhs_media"]:
            blocked.append("vhs")
        if blocked:
            missing_reason = f"requested engines are blocked: {', '.join(blocked)}"

    if missing_reason is None:
        return

    lines = [missing_reason + "."]
    if install_commands:
        lines.append("Run `python scripts/terminal_capture.py check` and use the suggested install commands.")
        for label, commands in install_commands.items():
            lines.append(f"[{label}]")
            lines.extend(commands)
    raise RuntimeError("\n".join(lines))


def render_ttyd(
    scenario_path: Path,
    scenario: dict[str, Any],
    output_root: Path,
    environment: dict[str, Any],
) -> Path:
    out_dir = output_root / "ttyd" / scenario["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    browser_path = environment["extras"]["system_browser"] or environment["extras"]["playwright_browser"]
    if browser_path:
        env["TERMINAL_CAPTURE_BROWSER"] = browser_path

    run_checked(
        [
            "node",
            str(SKILL_ROOT / "scripts" / "render_ttyd_scenario.js"),
            str(scenario_path),
            str(out_dir),
        ],
        SKILL_ROOT,
        env=env,
    )
    postprocess_screenshots(scenario, out_dir)
    return out_dir


def render_vhs(scenario: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    out_dir = output_root / "vhs" / scenario["name"]
    generated_dir = output_root / "generated"
    scenario_root = Path(scenario["cwd"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    tape_path = generated_dir / f'{scenario["name"]}.tape'
    tape_path.write_text(build_vhs_tape(scenario, out_dir))
    subprocess.run(["vhs", str(tape_path)], cwd=scenario_root, check=True)
    postprocess_screenshots(scenario, out_dir)
    return tape_path, out_dir


def render_command(args: argparse.Namespace) -> None:
    scenario_path = normalize_scenario_path(args.scenario)
    scenario = load_scenario(scenario_path)
    resolved_cwd = scenario_cwd(scenario_path, scenario, args.cwd)
    scenario["cwd"] = str(resolved_cwd)

    output_root = Path(args.output_root).resolve() if args.output_root else default_output_root(resolved_cwd)
    output_root.mkdir(parents=True, exist_ok=True)

    environment = detect_environment()
    ensure_engine_ready(args.engine, environment)

    created: list[tuple[str, Path]] = []
    if args.engine in {"ttyd", "all"}:
        created.append(("ttyd", render_ttyd(scenario_path, scenario, output_root, environment)))
    if args.engine in {"vhs", "all"}:
        tape_path, out_dir = render_vhs(scenario, output_root)
        created.append(("vhs_tape", tape_path))
        created.append(("vhs", out_dir))

    for label, path in created:
        print(f"{label}: {path}")


def extract_frames_command(args: argparse.Namespace) -> None:
    input_path = Path(args.media).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Media file not found: {input_path}")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_path.parent / f"{input_path.stem}-frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    times = [item.strip() for item in args.times.split(",") if item.strip()]
    created = []
    for index, timestamp in enumerate(times, start=1):
        output_path = output_dir / f"{input_path.stem}-{index:02d}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                timestamp,
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                "-update",
                "1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                "No frame was created at "
                f"{timestamp}. The media may be shorter than that timestamp; pick an earlier time. "
                f"Run `python scripts/terminal_capture.py probe-media {input_path}` if you need the exact duration."
            )
        created.append(output_path)

    for path in created:
        print(path)


def probe_media_command(args: argparse.Namespace) -> None:
    input_path = Path(args.media).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Media file not found: {input_path}")

    info = probe_media(input_path)
    print(f"Media: {info['path']}")
    if info["duration_seconds"] is not None:
        print(f"Duration: {info['duration_seconds']:.3f}s")
    else:
        print("Duration: unknown")
    if info["width"] and info["height"]:
        print(f"Resolution: {info['width']}x{info['height']}")
    if info["fps"] is not None:
        print(f"FPS: {info['fps']:.2f}")
    if info["codec"]:
        print(f"Codec: {info['codec']}")

    suggested = suggested_review_times(info["duration_seconds"])
    if suggested:
        print(f"Suggested review times: {','.join(suggested)}")


def _init_scenario_template(name: str) -> dict[str, Any]:
    """Minimal but actually-runnable scenario JSON the user can rerender immediately."""
    return {
        "name": name,
        "cwd": ".",
        "shell": ["bash", "--noprofile", "--norc", "-i"],
        "vhs": {
            "fontSize": 22,
            "width": 1280,
            "height": 760,
            "outputs": ["gif", "mp4"],
            "endHoldSeconds": 3,
        },
        "ttyd": {
            "fontSize": 20,
            "viewport": {"width": 1400, "height": 560, "deviceScaleFactor": 2},
        },
        "steps": [
            {
                "action": "command",
                "text": "echo hello world",
                "clear_before": True,
                "wait_for_text": "hello world",
                "timeout_ms": 5000,
                "result_shot": "01-hello",
            }
        ],
    }


def _init_render_script(name: str, engine: str) -> str:
    """Render-wrapper that resolves SKILL_ROOT for both Claude and Codex installs.

    The script is meant to be runnable from any cwd; it first chdirs to
    its own parent's parent (the project root, by convention), so the
    scenario path resolves correctly.

    Hardened against unset ``$HOME`` (systemd units, cron, minimal CI
    containers): if neither install path resolves, the script fails
    loudly with an actionable message instead of crashing later inside
    Python with a confusing "file not found" against an empty-prefix
    path like ``/.claude/...``.
    """
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '\n'
        '# Resolve SKILL_ROOT to either install location; allow override via env.\n'
        '# An explicit SKILL_ROOT skips the $HOME lookups entirely, which is\n'
        '# how cron / systemd / minimal CI containers (no HOME, no ~/.claude)\n'
        '# should drive this script.\n'
        'if [ -z "${SKILL_ROOT:-}" ]; then\n'
        '  if [ -z "${HOME:-}" ]; then\n'
        '    echo "Error: SKILL_ROOT is not set and HOME is empty." >&2\n'
        '    echo "  Set SKILL_ROOT to the terminal-capture-workflow checkout, e.g." >&2\n'
        '    echo "    SKILL_ROOT=/path/to/terminal-capture-workflow bash $0" >&2\n'
        '    exit 1\n'
        '  fi\n'
        '  SKILL_ROOT="$HOME/.claude/skills/terminal-capture-workflow"\n'
        '  if [ ! -d "$SKILL_ROOT" ]; then\n'
        '    SKILL_ROOT="$HOME/.codex/skills/terminal-capture-workflow"\n'
        '  fi\n'
        'fi\n'
        'if [ ! -d "$SKILL_ROOT" ]; then\n'
        '  echo "Error: SKILL_ROOT does not point at a directory: $SKILL_ROOT" >&2\n'
        '  echo "  Install the skill or override SKILL_ROOT explicitly." >&2\n'
        '  exit 1\n'
        'fi\n'
        '\n'
        'cd "$(dirname "$0")/.."\n'
        f'python3 "$SKILL_ROOT/scripts/terminal_capture.py" render {engine} '
        f'scenarios/{name}.json "$@"\n'
    )


def _init_setup_script() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '\n'
        "# Put repo-specific prep here. This runs BEFORE the render script.\n"
        "# Examples:\n"
        "#   pip install -e .\n"
        "#   source venv/bin/activate\n"
        "#   bash scripts/prefetch_fixtures.sh\n"
    )


def init_scenario(
    name: str,
    cwd: Path,
    engine: str = "all",
    with_setup: bool = False,
) -> dict[str, Path]:
    """Materialize the official scenarios/ + scripts/ three-piece layout.

    Creates ``<cwd>/scenarios/<name>.json`` and
    ``<cwd>/scripts/render_<name>.sh`` (always) plus
    ``<cwd>/scripts/setup_<name>.sh`` (when ``with_setup=True``). The
    parent directories are created on demand.

    :raises ValueError: if ``name`` does not match
        :data:`INIT_SCENARIO_NAME_PATTERN` or ``engine`` is not in
        :data:`INIT_VALID_ENGINES`.
    :raises FileExistsError: if any target path already exists. No
        partial writes are committed on conflict.
    :returns: A mapping of artifact kind (``"scenario"``,
        ``"render_script"``, and ``"setup_script"`` when applicable)
        to the absolute :class:`~pathlib.Path` that was written.
    """
    if not INIT_SCENARIO_NAME_PATTERN.match(name or ""):
        raise ValueError(
            f"Invalid scenario name: {name!r}. Use ASCII letters / digits / `-` / `_`, "
            "starting with a letter or digit."
        )
    if engine not in INIT_VALID_ENGINES:
        raise ValueError(
            f"Unknown engine: {engine!r}. Choose from {INIT_VALID_ENGINES}."
        )

    cwd = Path(cwd)
    scenarios_dir = cwd / "scenarios"
    scripts_dir = cwd / "scripts"
    scenario_path = scenarios_dir / f"{name}.json"
    render_path = scripts_dir / f"render_{name}.sh"
    setup_path = scripts_dir / f"setup_{name}.sh"

    # All-or-nothing existence check before any disk write.
    planned = [scenario_path, render_path]
    if with_setup:
        planned.append(setup_path)
    for path in planned:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")

    scenarios_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    scenario_path.write_text(
        json.dumps(_init_scenario_template(name), indent=2) + "\n"
    )

    render_path.write_text(_init_render_script(name, engine))
    render_path.chmod(render_path.stat().st_mode | 0o755)

    artifacts: dict[str, Path] = {
        "scenario": scenario_path,
        "render_script": render_path,
    }

    if with_setup:
        setup_path.write_text(_init_setup_script())
        setup_path.chmod(setup_path.stat().st_mode | 0o755)
        artifacts["setup_script"] = setup_path

    return artifacts


def init_command(args: argparse.Namespace) -> None:
    result = init_scenario(
        args.name,
        cwd=Path.cwd(),
        engine=args.engine,
        with_setup=args.with_setup,
    )
    for label, path in result.items():
        print(f"{label}: {path}")
    print("")
    print("Next steps:")
    print(f"  bash scripts/render_{args.name}.sh")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check, render, and inspect terminal capture scenarios for ttyd and VHS workflows."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Inspect local dependencies and print install commands.")
    check_parser.add_argument("--json", action="store_true", help="Print the environment report as JSON.")

    render_parser = subparsers.add_parser("render", help="Render a scenario through ttyd, VHS, or both.")
    render_parser.add_argument("engine", choices=["ttyd", "vhs", "all"])
    render_parser.add_argument("scenario", help="Path to a scenario JSON file.")
    render_parser.add_argument("--cwd", help="Override the scenario working directory.")
    render_parser.add_argument("--output-root", help="Directory where outputs should be written.")

    extract_parser = subparsers.add_parser("extract-frames", help="Extract representative frames for visual QA.")
    extract_parser.add_argument("media", help="Path to a GIF, MP4, or WebM file.")
    extract_parser.add_argument("--times", required=True, help="Comma-separated timestamps, for example 0.5,1.2,2.0")
    extract_parser.add_argument("--output-dir", help="Directory to store extracted PNG frames.")

    probe_parser = subparsers.add_parser("probe-media", help="Print duration and suggested review timestamps.")
    probe_parser.add_argument("media", help="Path to a GIF, MP4, or WebM file.")

    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold scenarios/<name>.json + scripts/render_<name>.sh in the current directory.",
    )
    init_parser.add_argument(
        "name",
        help="Scenario name (ASCII letters / digits / `-` / `_`, starting with a letter or digit).",
    )
    init_parser.add_argument(
        "--engine",
        default="all",
        choices=list(INIT_VALID_ENGINES),
        help="Engine the generated render script will pass to `render` (default: all).",
    )
    init_parser.add_argument(
        "--with-setup",
        action="store_true",
        help="Also scaffold scripts/setup_<name>.sh for repo-specific prep (env vars, fixture warm-up, ...).",
    )

    args = parser.parse_args()

    if args.command == "check":
        print_check_report(detect_environment(), args.json)
        return
    if args.command == "render":
        render_command(args)
        return
    if args.command == "extract-frames":
        extract_frames_command(args)
        return
    if args.command == "probe-media":
        probe_media_command(args)
        return
    if args.command == "init":
        init_command(args)
        return

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
