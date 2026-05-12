"""Regression and bug-fix tests for VHS escape and shell-command wrapping.

Tracks issue #3. Empirical VHS probing (see PR description) showed that
the issue body's first proposed fix — escaping `\\` to `\\\\` inside the
VHS Type string — is wrong: VHS does NOT unescape `\\\\`, it types two
literal backslashes, which collides with `field-notes.md`'s explicit
"don't double backslashes" rule and breaks real renders.

The real bug is purely on the wrap side: a forced break landing on a
literal `\\` produced ``chunk\\ \\`` (chunk-trailing backslash plus the
wrap-inserted ` \\` continuation marker), which the shell reads as
escaped-space + line-continuation. The fix is to roll the break index
back so the literal `\\` moves to the head of the next chunk.
"""

from terminal_capture import escape_vhs_text, wrap_shell_command_text


def test_escape_vhs_text_passes_literal_backslash_through_unchanged():
    """VHS Type strings preserve `\\` as-is (empirically confirmed against
    VHS). Doubling them on the way in would make VHS type two literal
    backslashes instead of one — exactly the failure mode that
    references/field-notes.md warns about. So escape_vhs_text must leave
    literal backslashes alone."""
    assert escape_vhs_text("end\\") == "end\\"
    assert escape_vhs_text(r"echo --regex '\d+'") == r"echo --regex '\d+'"


def test_escape_vhs_text_still_escapes_quotes_and_control_chars():
    """Regression: the existing replacements must keep working."""
    assert escape_vhs_text('say "hi"') == 'say \\"hi\\"'
    assert escape_vhs_text("a\tb") == "a\\tb"
    assert escape_vhs_text("a\rb") == "a\\rb"


def test_wrap_strips_chunk_trailing_backslash_before_continuation():
    """When the forced break position lands such that the chunk ends in a
    literal backslash, the wrapper must roll back so the trailing backslash
    becomes the leading character of the *next* chunk instead. Otherwise
    the rendered line ends in ``\\ \\`` — the shell reads that as
    escaped-space + line-continuation, which is not what the user typed.

    wrap_at_columns is clamped to a minimum of 20 inside the function; at
    that clamp with prompt_columns=0 the effective break length is 18, so
    placing the `\\` at index 17 forces the chunk to end on it.
    """
    text = "a" * 17 + "\\" + "b" * 5
    wrapped = wrap_shell_command_text(text, wrap_at_columns=20)
    for line in wrapped.split("\n"):
        if line.endswith(" \\"):
            chunk = line[:-2]
            assert not chunk.endswith("\\"), (
                f"Chunk ends in trailing backslash colliding with continuation: "
                f"chunk={chunk!r}, full line={line!r}"
            )

    # And the literal backslash from input must survive — when we strip the
    # wrap-added continuation markers / indent, we should recover the input.
    recovered = ""
    for line in wrapped.split("\n"):
        if line.endswith(" \\"):
            recovered += line[:-2]
        else:
            recovered += line.lstrip()
    assert recovered == text, (
        f"Wrap lost characters when fixing chunk-trailing backslash. "
        f"Expected {text!r}, got {recovered!r} from {wrapped!r}"
    )


def test_wrap_prefers_unquoted_whitespace_breakpoints():
    """The breakpoint logic must not record whitespace inside single- or
    double-quoted regions as a wrap point — so as long as the quoted region
    fits inside one wrap window, wrap should land on the unquoted whitespace
    before / after the quote rather than splitting the quote in two.

    (When the quoted region is *longer* than the wrap window, wrap currently
    has to fall back to a forced mid-quote break. That is a separate problem
    out of scope for issue #3.)
    """
    text = "first 'a b c' last more"
    wrapped = wrap_shell_command_text(text, wrap_at_columns=20)
    assert "'a b c'" in wrapped, (
        f"Quoted region was split across continuation lines: {wrapped!r}"
    )


def test_wrap_then_escape_keeps_exactly_one_trailing_backslash():
    """Composition invariant after the wrap fix: every non-final wrapped
    line, after passing through escape_vhs_text, must end in exactly one
    backslash — the wrap-inserted continuation marker. If two trailing
    backslashes leak through (chunk's own `\\` + the continuation marker)
    the shell parses the line as escaped-space + literal backslash, not
    backslash + line-continuation, and the render breaks."""
    text = "a" * 17 + "\\" + "b" * 5
    wrapped = wrap_shell_command_text(text, wrap_at_columns=20)
    lines = wrapped.split("\n")
    for line in lines[:-1]:  # every continuation line
        escaped = escape_vhs_text(line)
        trailing = len(escaped) - len(escaped.rstrip("\\"))
        assert trailing == 1, (
            f"Non-final wrapped line has {trailing} trailing backslash(es) "
            f"(must be exactly 1 — the continuation marker): {escaped!r}"
        )
