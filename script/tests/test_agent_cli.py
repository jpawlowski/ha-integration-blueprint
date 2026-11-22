"""Tests for script/.lib/agent_cli.sh, which runs a one-shot prompt through an installed, signed-in agent CLI."""

from pathlib import Path
import shutil
import subprocess

import pytest

LIB = Path(__file__).parents[1] / ".lib" / "agent_cli.sh"

# Answers the sign-in checks from STUB_SIGNED_IN, echoes every other call and its stdin.
STUB = """#!/bin/bash
name="$(basename "$0")"
signed_in=0
[[ " ${STUB_SIGNED_IN:-} " == *" $name "* ]] && signed_in=1
case "$name $1 $2" in
"claude auth status") [[ $signed_in == 1 ]] && echo '{"loggedIn": true}' || echo '{"loggedIn": false}'; exit 0 ;;
"codex login status") [[ $signed_in == 1 ]] && exit 0 || exit 1 ;;
"opencode auth list") [[ $signed_in == 1 ]] && echo "anthropic oauth" || echo "No authenticated integrations"; exit 0 ;;
esac
echo "$name $*"
for arg in "$@"; do
    case "$prev" in --output-last-message) echo "codex answer" >"$arg" ;; esac
    prev="$arg"
done
[[ -t 0 ]] || sed 's/^/stdin: /'
"""


def _bin(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    jq = shutil.which("jq")
    assert jq is not None
    (folder / "jq").symlink_to(jq)
    for name in names:
        stub = folder / name
        stub.write_text(STUB, encoding="utf-8")
        stub.chmod(0o755)
    return folder


def _run(tmp_path: Path, folder: Path, script: str, **env: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "prompt.md").write_text("Write the notes\n", encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; {script}'],
        cwd=tmp_path,
        env={"PATH": f"{folder}:/usr/bin:/bin", "HOME": str(tmp_path), **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_auto_skips_clis_that_are_not_signed_in(tmp_path: Path) -> None:
    """With every CLI installed, the first one signed in wins — not merely the first one installed."""
    folder = _bin(tmp_path, "claude", "codex", "copilot", "opencode")

    result = _run(tmp_path, folder, 'agent_resolve && echo "$AGENT_NAME"', STUB_SIGNED_IN="codex opencode")

    assert result.stdout.strip() == "codex"


@pytest.mark.unit
def test_the_session_it_runs_in_comes_first(tmp_path: Path) -> None:
    """Inside a Claude Code session, its own CLI is taken even when another one would come first."""
    folder = _bin(tmp_path, "claude", "codex")

    result = _run(tmp_path, folder, 'agent_resolve && echo "$AGENT_NAME"', CLAUDECODE="1", STUB_SIGNED_IN="codex")

    assert result.stdout.strip() == "claude"


@pytest.mark.unit
def test_copilot_is_the_fallback_when_nothing_else_is_signed_in(tmp_path: Path) -> None:
    """Copilot cannot report its sign-in without a request, so it is tried after every CLI that can."""
    folder = _bin(tmp_path, "claude", "copilot")

    result = _run(tmp_path, folder, 'agent_resolve && echo "$AGENT_NAME"')

    assert result.stdout.strip() == "copilot"


@pytest.mark.unit
def test_nothing_signed_in_names_how_to_sign_in(tmp_path: Path) -> None:
    """The failure lists each installed CLI with its own sign-in command."""
    folder = _bin(tmp_path, "claude", "codex", "opencode")

    result = _run(tmp_path, folder, "agent_resolve")

    assert result.returncode == 1
    assert "codex: codex login" in result.stderr
    assert "opencode: opencode auth login" in result.stderr
    assert "claude: run claude and type /login" in result.stderr


@pytest.mark.unit
def test_any_takes_the_first_installed_for_a_session(tmp_path: Path) -> None:
    """An interactive session lets the user sign in there, so --any does not ask."""
    folder = _bin(tmp_path, "codex", "opencode")

    result = _run(tmp_path, folder, 'agent_resolve --any && echo "$AGENT_NAME"')

    assert result.stdout.strip() == "codex"


@pytest.mark.parametrize(
    ("cli", "signed_in", "message"),
    [
        pytest.param("codex", "", "it is not signed in — codex login", id="named-but-signed-out"),
        pytest.param("opencode", "opencode", "opencode is not installed", id="named-but-missing"),
    ],
)
@pytest.mark.unit
def test_a_named_cli_never_falls_back_to_another(tmp_path: Path, cli: str, signed_in: str, message: str) -> None:
    """Asking for one CLI fails with the reason rather than quietly using a different one."""
    folder = _bin(tmp_path, "claude", "codex")

    result = _run(tmp_path, folder, "agent_resolve", AGENT_CLI=cli, STUB_SIGNED_IN=f"claude {signed_in}")

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("cli", "expected"),
    [
        pytest.param("claude", "claude --print --tools  --model m1", id="claude"),
        pytest.param("copilot", "copilot --silent --deny-tool=write --deny-tool=shell --model m1", id="copilot"),
        pytest.param("opencode", "opencode run --agent plan --archived --model m1 --file prompt.md", id="opencode"),
    ],
)
@pytest.mark.unit
def test_prompt_runs_without_tools_and_with_the_model(tmp_path: Path, cli: str, expected: str) -> None:
    """Each CLI gets its own non-interactive flags, no tools, and AGENT_MODEL when it is set."""
    folder = _bin(tmp_path, cli)

    result = _run(
        tmp_path, folder, "agent_resolve && agent_prompt prompt.md", AGENT_CLI=cli, AGENT_MODEL="m1", STUB_SIGNED_IN=cli
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(expected)


@pytest.mark.unit
def test_codex_prints_only_its_last_message(tmp_path: Path) -> None:
    """Codex exec logs its progress; only the final answer reaches the caller."""
    folder = _bin(tmp_path, "codex")

    result = _run(tmp_path, folder, "agent_resolve && agent_prompt prompt.md", STUB_SIGNED_IN="codex")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "codex answer\n"


@pytest.mark.unit
def test_no_model_leaves_the_clis_default(tmp_path: Path) -> None:
    """An unset AGENT_MODEL passes no --model at all."""
    folder = _bin(tmp_path, "claude")

    result = _run(tmp_path, folder, "agent_resolve && agent_prompt prompt.md", STUB_SIGNED_IN="claude")

    assert "--model" not in result.stdout
    assert "stdin: Write the notes" in result.stdout
