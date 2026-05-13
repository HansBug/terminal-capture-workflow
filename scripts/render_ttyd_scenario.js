const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

// scrollback bounds how far back the xterm.js buffer (and therefore
// buffer-based waitForText) can match. Raised from xterm.js's built-in
// 1000 so most long-output captures work without opting in; scenarios
// can override via `ttyd.scrollback`.
const TTYD_DEFAULT_SCROLLBACK = 5000;

// Default regex matched against the rendered terminal text to detect that
// a shell prompt has returned after a command finishes. Mirrors
// DEFAULT_PROMPT_REGEX in scripts/terminal_capture.py — keep these in sync.
const DEFAULT_PROMPT_REGEX = "[\\$#%▶❯>]\\s*$";

const BROWSER_CANDIDATES = [
  "google-chrome",
  "google-chrome-stable",
  "chromium",
  "chromium-browser",
];
const KEY_ALIASES = new Map([
  ["ctrl", "Control"],
  ["control", "Control"],
  ["alt", "Alt"],
  ["shift", "Shift"],
  ["meta", "Meta"],
  ["cmd", "Meta"],
  ["command", "Meta"],
  ["esc", "Escape"],
  ["escape", "Escape"],
  ["enter", "Enter"],
  ["return", "Enter"],
  ["tab", "Tab"],
  ["pgup", "PageUp"],
  ["pageup", "PageUp"],
  ["pgdn", "PageDown"],
  ["pgdown", "PageDown"],
  ["pagedown", "PageDown"],
  ["del", "Delete"],
  ["delete", "Delete"],
  ["ins", "Insert"],
  ["insert", "Insert"],
  ["home", "Home"],
  ["end", "End"],
  ["backspace", "Backspace"],
  ["up", "ArrowUp"],
  ["arrowup", "ArrowUp"],
  ["down", "ArrowDown"],
  ["arrowdown", "ArrowDown"],
  ["left", "ArrowLeft"],
  ["arrowleft", "ArrowLeft"],
  ["right", "ArrowRight"],
  ["arrowright", "ArrowRight"],
  ["spacebar", " "],
  ["space", " "],
]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function findExecutableOnPath(name) {
  const pathValue = process.env.PATH || "";
  for (const dir of pathValue.split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function resolveBrowserExecutable() {
  if (process.env.TERMINAL_CAPTURE_BROWSER && fs.existsSync(process.env.TERMINAL_CAPTURE_BROWSER)) {
    return process.env.TERMINAL_CAPTURE_BROWSER;
  }

  for (const candidate of BROWSER_CANDIDATES) {
    const resolved = findExecutableOnPath(candidate);
    if (resolved) {
      return resolved;
    }
  }

  return null;
}

async function launchBrowser() {
  const executablePath = resolveBrowserExecutable();
  const launchOptions = { headless: true };

  if (executablePath) {
    try {
      return await chromium.launch({ ...launchOptions, executablePath });
    } catch (error) {
      // Fall through to the default Playwright browser.
    }
  }

  try {
    return await chromium.launch(launchOptions);
  } catch (error) {
    throw new Error(
      "Unable to launch a browser for ttyd rendering. Install a system Chrome/Chromium browser or run `npm install` and `npx playwright install chromium` in the skill directory.",
    );
  }
}

async function waitForServer(url, timeoutMs = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {}
    await sleep(200);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function waitForText(page, pattern, timeoutMs = 10000, flags = "m") {
  // Fail fast if the xterm.js Buffer API is not reachable. Every
  // supported ttyd build (>=1.7.x) exposes `window.term`, and
  // waitForText is only ever called after the page has been focused,
  // so reaching here without a usable buffer means the upstream API
  // has shifted. Surface that loudly rather than silently sliding
  // back into the viewport-bounded mode this code path was written
  // to remove — a downgrade would just resurrect the original
  // wait-race bug and hide behind a generic Playwright timeout.
  const hasTermBuffer = await page.evaluate(() => {
    const term = window.term;
    return !!(term && term.buffer && term.buffer.active);
  });
  if (!hasTermBuffer) {
    throw new Error(
      "xterm.js Buffer API not reachable via window.term — cannot scan ttyd scrollback for wait_for_text. " +
        "This usually indicates a ttyd / xterm.js upgrade renamed the global; rerun the canonical reproducer in references/field-notes.md.",
    );
  }

  await page.waitForFunction(
    ({ source, regexFlags }) => {
      const buf = window.term.buffer.active;
      let text = "";
      const limit = buf.length;
      for (let i = 0; i < limit; i += 1) {
        const line = buf.getLine(i);
        if (!line) continue;
        text += line.translateToString(false) + "\n";
      }
      return new RegExp(source, regexFlags).test(text);
    },
    { source: pattern, regexFlags: flags },
    { timeout: timeoutMs },
  );
}

function resolveWaitPromptPattern(value) {
  if (value === true) return DEFAULT_PROMPT_REGEX;
  if (typeof value === "string") return value || null;
  if (value === false || value === null || value === undefined) return null;
  throw new Error(
    `wait_for_prompt must be a bool or a string regex, got ${typeof value}: ${JSON.stringify(value)}`,
  );
}


function resolveWaitPattern(step) {
  if (step.pattern_by_engine && step.pattern_by_engine.ttyd) {
    return step.pattern_by_engine.ttyd;
  }
  if (step.wait_for_text_by_engine && step.wait_for_text_by_engine.ttyd) {
    return step.wait_for_text_by_engine.ttyd;
  }
  return step.pattern || step.wait_for_text;
}

async function focusTerminal(page) {
  await page.locator(".xterm-helper-textarea").focus();
}

async function capture(page, outDir, name) {
  await page.locator(".xterm-rows").screenshot({
    path: path.join(outDir, `${name}.png`),
  });
}

function normalizeKeyPart(part) {
  const trimmed = part.trim();
  if (!trimmed) {
    throw new Error(`Invalid key part: ${part}`);
  }
  if (trimmed.length === 1) {
    return trimmed;
  }
  return KEY_ALIASES.get(trimmed.toLowerCase()) || trimmed;
}

function normalizeKey(key) {
  if (!key || typeof key !== "string") {
    throw new Error(`Invalid key: ${key}`);
  }

  const parts = key.trim().split("+");
  return parts.map((part) => normalizeKeyPart(part)).join("+");
}

async function pressKey(page, key, repeat = 1, delayMs = 0) {
  await focusTerminal(page);
  for (let idx = 0; idx < repeat; idx += 1) {
    await page.keyboard.press(normalizeKey(key), { delay: delayMs });
  }
}

function splitTextLines(text) {
  return String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}

function commandWrapBreakpoints(text) {
  const points = [];
  let inSingle = false;
  let inDouble = false;
  let escaped = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\" && !inSingle) {
      escaped = true;
      continue;
    }
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (char === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }
    if (/\s/.test(char) && !inSingle && !inDouble) {
      points.push(index);
    }
  }

  return new Set(points);
}

function wrapShellCommandText(
  text,
  wrapAtColumns,
  continuationIndent = 2,
  promptColumns = 0,
  continuationPromptColumns = 0,
) {
  const normalized = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n+$/, "");
  if (normalized.includes("\n")) {
    return normalized;
  }

  const maxColumns = Math.max(20, Number(wrapAtColumns) || 0);
  const indentWidth = Math.max(0, Number(continuationIndent) || 0);
  const firstPromptWidth = Math.max(0, Number(promptColumns) || 0);
  const nextPromptWidth = Math.max(0, Number(continuationPromptColumns) || 0);
  const indent = " ".repeat(indentWidth);
  const safePoints = commandWrapBreakpoints(normalized);
  const lines = [];
  let start = 0;
  let currentLimit = Math.max(12, maxColumns - firstPromptWidth - 2);

  while (normalized.length - start > currentLimit) {
    const end = start + currentLimit;
    let breakIndex = -1;

    for (let index = end; index > start; index -= 1) {
      if (safePoints.has(index - 1)) {
        breakIndex = index - 1;
        break;
      }
    }

    if (breakIndex < start) {
      breakIndex = end;
      while (breakIndex > start && /\s/.test(normalized[breakIndex - 1])) {
        breakIndex -= 1;
      }
      if (breakIndex <= start) {
        return normalized;
      }
    }

    let chunk = normalized.slice(start, breakIndex).replace(/\s+$/, "");
    if (!chunk) {
      return normalized;
    }

    while (chunk.endsWith("\\")) {
      chunk = chunk.slice(0, -1);
      breakIndex -= 1;
    }
    if (!chunk) {
      return normalized;
    }

    lines.push(`${chunk} \\`);
    start = breakIndex;
    while (start < normalized.length && /\s/.test(normalized[start])) {
      start += 1;
    }
    currentLimit = Math.max(12, maxColumns - nextPromptWidth - indentWidth - 2);
  }

  lines.push(`${lines.length ? indent : ""}${normalized.slice(start)}`);
  if (lines.length > 1) {
    return [lines[0], ...lines.slice(1).map((line) => `${indent}${line}`)].join("\n");
  }
  return lines[0];
}

function resolveCommandText(step) {
  if (step.wrap_at_columns != null) {
    return wrapShellCommandText(
      step.text,
      step.wrap_at_columns,
      step.wrap_indent ?? 2,
      step.prompt_columns ?? 0,
      step.continuation_prompt_columns ?? 0,
    );
  }
  return step.text;
}

async function typeText(page, text, delayMs) {
  await focusTerminal(page);
  const parts = splitTextLines(text);
  for (let idx = 0; idx < parts.length; idx += 1) {
    if (parts[idx]) {
      await page.keyboard.type(parts[idx], { delay: delayMs });
    }
    if (idx !== parts.length - 1) {
      await page.keyboard.press("Enter");
    }
  }
}

async function pasteText(page, text, delayMs = 0) {
  if (delayMs > 0) {
    await typeText(page, text, delayMs);
    return;
  }
  await focusTerminal(page);
  const parts = splitTextLines(text);
  for (let idx = 0; idx < parts.length; idx += 1) {
    if (parts[idx]) {
      await page.keyboard.insertText(parts[idx]);
    }
    if (idx !== parts.length - 1) {
      await page.keyboard.press("Enter");
    }
  }
}

async function runInputEvent(page, event, typingDelayMs) {
  switch (event.kind) {
    case "sleep":
      await sleep(event.ms);
      return;
    case "text":
      await typeText(page, event.text, event.delay_ms ?? typingDelayMs);
      return;
    case "paste":
      await pasteText(page, event.text, event.delay_ms ?? 0);
      return;
    case "press":
      await pressKey(page, event.key, event.repeat || 1, event.delay_ms || 0);
      return;
    default:
      throw new Error(`Unsupported input event kind: ${event.kind}`);
  }
}

async function runInputStep(page, step, typingDelayMs) {
  for (const event of step.events || []) {
    await runInputEvent(page, event, typingDelayMs);
  }
}

async function runCommandStep(page, outDir, step, typingDelayMs) {
  if (step.clear_before) {
    await pressKey(page, "Control+L");
    await sleep(120);
  }

  await typeText(page, resolveCommandText(step), step.delay_ms ?? typingDelayMs);

  if (step.typed_shot) {
    await capture(page, outDir, step.typed_shot);
  }

  await page.keyboard.press("Enter");

  const waitPattern = resolveWaitPattern(step);
  const promptPattern = resolveWaitPromptPattern(step.wait_for_prompt);
  const timeoutMs = step.timeout_ms || 10000;
  if (waitPattern) {
    await waitForText(page, waitPattern, timeoutMs, step.flags || "m");
  }
  if (promptPattern) {
    // After wait_for_text fires (summary visible) we additionally wait
    // for the shell prompt to return — same "wait on summary AND on
    // prompt" guarantee field-notes.md recommends. The pattern uses
    // multiline mode so it matches a prompt on its own line.
    await waitForText(page, promptPattern, timeoutMs, "m");
  }
  if (!waitPattern && !promptPattern) {
    await sleep(step.result_delay_ms || 900);
  }

  if (step.result_shot) {
    await capture(page, outDir, step.result_shot);
  }
}

async function runStep(page, outDir, step, typingDelayMs) {
  switch (step.action) {
    case "sleep":
      await sleep(step.ms);
      return;
    case "type":
      await typeText(page, step.text, step.delay_ms ?? typingDelayMs);
      return;
    case "paste":
      await pasteText(page, step.text, step.delay_ms ?? 0);
      return;
    case "press":
      await pressKey(page, step.key, step.repeat || 1, step.delay_ms || 0);
      return;
    case "input":
      await runInputStep(page, step, typingDelayMs);
      return;
    case "wait_for_text":
      await waitForText(page, resolveWaitPattern(step), step.timeout_ms || 10000, step.flags || "m");
      return;
    case "wait_for_prompt": {
      const promptPattern = resolveWaitPromptPattern(step.prompt);
      if (!promptPattern) {
        throw new Error(
          "wait_for_prompt action requires `prompt` (true or a non-empty regex string).",
        );
      }
      await waitForText(page, promptPattern, step.timeout_ms || 10000, "m");
      return;
    }
    case "screenshot":
      await capture(page, outDir, step.name);
      return;
    case "command":
      await runCommandStep(page, outDir, step, typingDelayMs);
      return;
    case "hide":
    case "show":
      return;
    case "raw_vhs":
      throw new Error("raw_vhs is VHS-only. Render with the VHS engine or use the generic input model for ttyd.");
    default:
      throw new Error(`Unsupported action: ${step.action}`);
  }
}

async function main() {
  const scenarioPath = process.argv[2];
  const outDir = process.argv[3];

  if (!scenarioPath || !outDir) {
    throw new Error("Usage: node render_ttyd_scenario.js <scenario.json> <out-dir>");
  }

  const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
  const ttydConfig = scenario.ttyd || {};
  const viewport = ttydConfig.viewport || {
    width: 1400,
    height: 560,
    deviceScaleFactor: 2,
  };
  const typingDelayMs = ttydConfig.typingDelayMs || 20;
  const port = 15000 + (process.pid % 10000);
  const clientOptions = [
    ["fontSize", String(ttydConfig.fontSize || 20)],
    ["cursorBlink", String(ttydConfig.cursorBlink !== false)],
    ["rendererType", ttydConfig.rendererType || "dom"],
    [
      "scrollback",
      String(
        ttydConfig.scrollback != null
          ? ttydConfig.scrollback
          : TTYD_DEFAULT_SCROLLBACK,
      ),
    ],
  ];

  if (ttydConfig.theme) {
    clientOptions.push(["theme", JSON.stringify(ttydConfig.theme)]);
  }

  for (const [key, value] of ttydConfig.extraClientOptions || []) {
    clientOptions.push([key, value]);
  }

  fs.mkdirSync(outDir, { recursive: true });

  const ttydArgs = ["-p", String(port), "-W", "-w", scenario.cwd || process.cwd()];
  for (const [key, value] of clientOptions) {
    ttydArgs.push("-t", `${key}=${value}`);
  }
  ttydArgs.push(...(scenario.shell || ["bash", "--noprofile", "--norc", "-i"]));

  const ttyd = spawn("ttyd", ttydArgs, {
    cwd: scenario.cwd || process.cwd(),
    stdio: ["ignore", "pipe", "pipe"],
  });

  let serverLog = "";
  ttyd.stdout.on("data", (buf) => {
    serverLog += buf.toString();
  });
  ttyd.stderr.on("data", (buf) => {
    serverLog += buf.toString();
  });

  const cleanup = () => {
    if (!ttyd.killed) {
      ttyd.kill("SIGTERM");
    }
  };

  process.on("exit", cleanup);
  process.on("SIGINT", () => {
    cleanup();
    process.exit(130);
  });

  try {
    await waitForServer(`http://127.0.0.1:${port}`);

    const browser = await launchBrowser();
    const page = await browser.newPage({
      viewport: {
        width: viewport.width,
        height: viewport.height,
      },
      deviceScaleFactor: viewport.deviceScaleFactor || 2,
    });

    await page.goto(`http://127.0.0.1:${port}`, { waitUntil: "networkidle" });
    await page.locator(".xterm").waitFor();
    await focusTerminal(page);
    await sleep(400);

    for (const step of scenario.steps || []) {
      await runStep(page, outDir, step, typingDelayMs);
    }

    await browser.close();
    cleanup();
    process.stdout.write(`${outDir}\n`);
  } catch (error) {
    cleanup();
    process.stderr.write(`${serverLog}\n`);
    throw error;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
