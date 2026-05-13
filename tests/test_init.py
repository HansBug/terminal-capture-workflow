"""Tests for the ``init`` subcommand's ``init_scenario`` helper.

Tracks issue #5. The helper officially codifies the
``scenarios/<name>.json`` + ``scripts/render_<name>.sh`` (+ optional
``scripts/setup_<name>.sh``) three-piece layout that downstream
consumers (pyfcstm-2, pyplantuml, animedex …) each reinvented by hand,
so that a fresh project gets a sane, runnable starter from one command.
"""

import json
import os
import re
import stat

import pytest

from terminal_capture import init_scenario


def _executable(path):
    return bool(os.stat(path).st_mode & stat.S_IXUSR)


def test_init_creates_scenario_and_render_for_vhs(tmp_path):
    """The minimal happy path: a single ``init`` call drops a scenario
    JSON and a render shell wrapper, wired together by name and engine."""
    result = init_scenario("my-demo", cwd=tmp_path, engine="vhs")

    scenario_path = tmp_path / "scenarios" / "my-demo.json"
    render_path = tmp_path / "scripts" / "render_my-demo.sh"

    assert scenario_path.exists(), "scenarios/my-demo.json should be created"
    assert render_path.exists(), "scripts/render_my-demo.sh should be created"
    assert _executable(render_path), "render script must be executable"

    scenario = json.loads(scenario_path.read_text())
    assert scenario["name"] == "my-demo"
    assert isinstance(scenario.get("steps"), list) and scenario["steps"], (
        "template must include at least one runnable step"
    )

    render_text = render_path.read_text()
    assert "scenarios/my-demo.json" in render_text
    assert re.search(r"\brender\s+vhs\b", render_text), (
        "render script must invoke the requested engine"
    )

    assert set(result) == {"scenario", "render_script"}
    assert result["scenario"] == scenario_path
    assert result["render_script"] == render_path


@pytest.mark.parametrize("engine", ["ttyd", "vhs", "all"])
def test_init_accepts_supported_engines(tmp_path, engine):
    init_scenario("foo", cwd=tmp_path, engine=engine)
    render_text = (tmp_path / "scripts" / "render_foo.sh").read_text()
    assert re.search(rf"\brender\s+{engine}\b", render_text)


def test_init_with_setup_creates_executable_setup_script(tmp_path):
    result = init_scenario("foo", cwd=tmp_path, engine="vhs", with_setup=True)
    setup_path = tmp_path / "scripts" / "setup_foo.sh"
    assert setup_path.exists()
    assert _executable(setup_path)
    assert result["setup_script"] == setup_path


def test_init_without_setup_does_not_create_setup_script(tmp_path):
    init_scenario("foo", cwd=tmp_path, engine="vhs", with_setup=False)
    assert not (tmp_path / "scripts" / "setup_foo.sh").exists()


def test_init_refuses_to_overwrite_existing_scenario(tmp_path):
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "foo.json").write_text('{"existing": true}')
    with pytest.raises(FileExistsError, match="foo.json"):
        init_scenario("foo", cwd=tmp_path, engine="vhs")
    # And the existing file must be untouched.
    assert json.loads((tmp_path / "scenarios" / "foo.json").read_text()) == {
        "existing": True
    }


def test_init_refuses_to_overwrite_existing_render_script(tmp_path):
    (tmp_path / "scripts").mkdir()
    existing = "#!/usr/bin/env bash\necho already here\n"
    (tmp_path / "scripts" / "render_foo.sh").write_text(existing)
    with pytest.raises(FileExistsError, match="render_foo.sh"):
        init_scenario("foo", cwd=tmp_path, engine="vhs")
    assert (tmp_path / "scripts" / "render_foo.sh").read_text() == existing


def test_init_with_setup_refuses_to_overwrite_existing_setup(tmp_path):
    (tmp_path / "scripts").mkdir()
    existing = "#!/usr/bin/env bash\nexport KEY=preset\n"
    (tmp_path / "scripts" / "setup_foo.sh").write_text(existing)
    with pytest.raises(FileExistsError, match="setup_foo.sh"):
        init_scenario("foo", cwd=tmp_path, engine="vhs", with_setup=True)
    assert (tmp_path / "scripts" / "setup_foo.sh").read_text() == existing


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "../escape",
        "foo/bar",
        "with space",
        ".hidden",
        "-leading-dash",
        "_leading-underscore",  # leading underscore — not a valid identifier-style name
    ],
)
def test_init_rejects_invalid_scenario_names(tmp_path, bad_name):
    with pytest.raises(ValueError, match="scenario name"):
        init_scenario(bad_name, cwd=tmp_path, engine="vhs")


def test_init_rejects_unknown_engine(tmp_path):
    with pytest.raises(ValueError, match="engine"):
        init_scenario("foo", cwd=tmp_path, engine="quartz")


def test_init_creates_parent_directories_if_missing(tmp_path):
    """`scenarios/` and `scripts/` should be auto-created when absent."""
    assert not (tmp_path / "scenarios").exists()
    assert not (tmp_path / "scripts").exists()
    init_scenario("foo", cwd=tmp_path, engine="vhs", with_setup=True)
    assert (tmp_path / "scenarios").is_dir()
    assert (tmp_path / "scripts").is_dir()


def test_init_render_script_resolves_skill_root_via_env_or_known_paths(tmp_path):
    """The render script must be portable: it should use SKILL_ROOT env
    var first, then fall back to known Claude / Codex install locations,
    so the same scripts/render_<name>.sh works on both agent CLIs."""
    init_scenario("foo", cwd=tmp_path, engine="vhs")
    render_text = (tmp_path / "scripts" / "render_foo.sh").read_text()
    assert "SKILL_ROOT" in render_text
    assert ".claude/skills/terminal-capture-workflow" in render_text
    assert ".codex/skills/terminal-capture-workflow" in render_text


def test_init_render_script_fails_loudly_when_home_and_skill_root_unset(tmp_path):
    """systemd / cron / minimal CI containers run without ``$HOME``.
    The generated render script must reject that state with an actionable
    message instead of silently expanding to ``/.claude/...`` and
    crashing later inside Python with a confusing "file not found"."""
    init_scenario("foo", cwd=tmp_path, engine="vhs")
    render_text = (tmp_path / "scripts" / "render_foo.sh").read_text()
    assert "SKILL_ROOT is not set and HOME is empty" in render_text
    assert "SKILL_ROOT does not point at a directory" in render_text


@pytest.mark.parametrize("name", ["Foo", "MyDemo", "CamelCaseName", "A1", "X_y-Z"])
def test_init_accepts_uppercase_and_mixed_case_names(tmp_path, name):
    """The name regex allows ASCII uppercase as well as digits, ``-``,
    and ``_`` mid-string. Pin a few CamelCase / mixed-case cases so a
    future tightening can't silently break them."""
    init_scenario(name, cwd=tmp_path, engine="vhs")
    assert (tmp_path / "scenarios" / f"{name}.json").exists()
    assert (tmp_path / "scripts" / f"render_{name}.sh").exists()
