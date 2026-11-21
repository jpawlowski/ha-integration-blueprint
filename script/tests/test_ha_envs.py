"""Tests for script/.lib/ha_envs.sh, with stubbed version resolution and venv builds."""

import os
from pathlib import Path
import subprocess

import pytest

LIB = Path(__file__).parents[1] / ".lib"
STUBS = """
target_ha_version() { local -n _r="$1"; _r="$STUB_MINIMUM"; }
resolve_ha_version() {
    local -n _r="$1"
    case "$2" in latest) _r="$STUB_LATEST" ;; beta) _r="$STUB_BETA" ;; *) _r="$2" ;; esac
}
ha_envs_create_venv() { mkdir -p "$1/bin" "$1/lib"; echo "home = stub" >"$1/pyvenv.cfg"; }
ha_envs_install() {
    [[ " ${STUB_FAIL:-} " == *" $2 "* ]] && return 1
    echo "$2" >"$1/bin/version"
}
"""
VERSIONS = {"STUB_MINIMUM": "2026.11.2", "STUB_LATEST": "2026.11.2", "STUB_BETA": "2026.12.0b1"}


def _bash(workdir: Path, commands: str, **stubs: str) -> subprocess.CompletedProcess[str]:
    """Run commands with the library and the stubs loaded, in workdir, outside any dev container or CI."""
    env = {k: v for k, v in os.environ.items() if k not in {"REMOTE_CONTAINERS", "CODESPACES", "GITHUB_ACTIONS"}}
    script = "\n".join(
        [
            "set -euo pipefail",
            *(f"source {LIB / name}" for name in ("output.sh", "download.sh", "ha_version.sh", "ha_envs.sh")),
            STUBS,
            commands,
        ]
    )
    return subprocess.run(
        ["bash", "-c", script],
        cwd=workdir,
        env={**env, **VERSIONS, **stubs},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A project directory with a hacs.json on the 2026.11 release."""
    (tmp_path / "hacs.json").write_text('{"homeassistant": "2026.11.0"}\n', encoding="utf-8")
    return tmp_path


def _root(workdir: Path) -> Path:
    return workdir / ".local" / "ha-venv"


def _slot(workdir: Path, slot: str) -> str:
    return (_root(workdir) / "slots" / slot).readlink().name


def _versions(workdir: Path) -> list[str]:
    return sorted(path.name for path in (_root(workdir) / "versions").iterdir())


@pytest.mark.unit
def test_minimum_and_latest_on_one_version_share_a_venv(workdir: Path) -> None:
    """Two slots on the same release point at one venv; the beta always gets its own."""
    result = _bash(workdir, "for s in minimum latest beta; do ha_envs_refresh $s; done; ha_envs_prune")

    assert result.returncode == 0, result.stderr
    assert _slot(workdir, "minimum") == _slot(workdir, "latest") == "2026.11.2"
    assert _slot(workdir, "beta") == "2026.12.0b1"
    assert _versions(workdir) == ["2026.11.2", "2026.12.0b1"]


@pytest.mark.unit
def test_beta_stays_a_pre_release_while_older_than_latest(workdir: Path) -> None:
    """Right after a stable release the beta keeps the last pre-release instead of taking the release."""
    result = _bash(
        workdir, "ha_envs_refresh latest; ha_envs_refresh beta", STUB_LATEST="2026.12.0", STUB_BETA="2026.12.0rc2"
    )

    assert result.returncode == 0, result.stderr
    assert _slot(workdir, "latest") == "2026.12.0"
    assert _slot(workdir, "beta") == "2026.12.0rc2"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("slot", "stubs"),
    [("beta", {"STUB_BETA": "2026.12.0"}), ("latest", {"STUB_LATEST": "2026.12.0b1"})],
    ids=["beta-given-a-release", "latest-given-a-pre-release"],
)
def test_a_slot_never_takes_the_other_kind(workdir: Path, slot: str, stubs: dict[str, str]) -> None:
    """Beta only ever holds a pre-release and latest only a release; anything else fails and builds nothing."""
    result = _bash(workdir, f"ha_envs_refresh {slot}", **stubs)

    assert result.returncode == 1
    assert not (_root(workdir) / "slots" / slot).exists()
    assert not (_root(workdir) / "versions").exists()


@pytest.mark.unit
def test_a_refresh_moves_the_slot_forward_and_prunes_the_old_version(workdir: Path) -> None:
    """A newer beta replaces the previous one, which is deleted once nothing points at it."""
    _bash(workdir, "ha_envs_refresh beta")

    result = _bash(workdir, "ha_envs_refresh beta; ha_envs_prune", STUB_BETA="2026.12.0b2")

    assert result.returncode == 0, result.stderr
    assert _slot(workdir, "beta") == "2026.12.0b2"
    assert _versions(workdir) == ["2026.12.0b2"]


@pytest.mark.unit
def test_a_failed_build_keeps_the_previous_version(workdir: Path) -> None:
    """The slot moves only after its new version built; the unfinished build is removed."""
    _bash(workdir, "ha_envs_refresh beta")

    result = _bash(workdir, "ha_envs_refresh beta", STUB_BETA="2026.12.0b2", STUB_FAIL="2026.12.0b2")

    assert result.returncode == 1
    assert _slot(workdir, "beta") == "2026.12.0b1"
    assert _versions(workdir) == ["2026.12.0b1"]


@pytest.mark.unit
def test_use_mirrors_the_active_slot_at_the_root(workdir: Path) -> None:
    """The root's bin and pyvenv.cfg follow the active slot, so every existing venv path keeps working."""
    _bash(workdir, "ha_envs_refresh minimum; ha_envs_refresh beta; ha_envs_use minimum")
    root = _root(workdir)
    assert (root / "bin" / "version").read_text(encoding="utf-8") == "2026.11.2\n"
    assert (root / "pyvenv.cfg").is_symlink()

    _bash(workdir, "ha_envs_use beta")

    assert (root / "bin" / "version").read_text(encoding="utf-8") == "2026.12.0b1\n"
    assert _bash(workdir, "ha_envs_current_slot").stdout == "beta\n"


@pytest.mark.unit
def test_use_refuses_a_slot_that_is_not_installed(workdir: Path) -> None:
    """Switching to a missing slot says how to add it and leaves the active one alone."""
    _bash(workdir, "ha_envs_refresh minimum; ha_envs_use minimum")

    result = _bash(workdir, "ha_envs_use latest")

    assert result.returncode == 1
    assert "script/ha-env add latest" in result.stdout + result.stderr
    assert _bash(workdir, "ha_envs_current_slot").stdout == "minimum\n"


@pytest.mark.unit
def test_remove_keeps_minimum_and_the_active_slot(workdir: Path) -> None:
    """Minimum and the active slot cannot be removed; another slot can, and its venv goes with the next prune."""
    _bash(workdir, "for s in minimum latest beta; do ha_envs_refresh $s; done; ha_envs_use latest")

    assert _bash(workdir, "ha_envs_remove minimum").returncode == 1
    assert _bash(workdir, "ha_envs_remove latest").returncode == 1
    result = _bash(workdir, "ha_envs_remove beta; ha_envs_prune")

    assert result.returncode == 0, result.stderr
    assert _bash(workdir, "ha_envs_installed").stdout.split() == ["latest", "minimum"]
    assert _versions(workdir) == ["2026.11.2"]


@pytest.mark.unit
def test_migrate_clears_the_single_venv_of_the_old_layout(workdir: Path) -> None:
    """A root that is itself a venv is emptied, so its slots can be built; a migrated root is left alone."""
    root = _root(workdir)
    (root / "bin").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = old\n", encoding="utf-8")
    (root / ".ha-version").write_text("2026.10.4\n", encoding="utf-8")

    result = _bash(workdir, "ha_envs_migrate; ha_envs_refresh minimum; ha_envs_use minimum; ha_envs_migrate")

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in root.iterdir() if not path.is_symlink()) == ["slots", "versions"]
    assert (root / "bin" / "version").read_text(encoding="utf-8") == "2026.11.2\n"


@pytest.mark.unit
def test_notice_names_a_stale_refresh_and_a_minimum_off_the_hacs_release(workdir: Path) -> None:
    """Both notices need no network; a fresh refresh on the hacs.json release prints nothing."""
    _bash(workdir, "ha_envs_refresh minimum; ha_envs_mark_refreshed")
    assert _bash(workdir, "ha_envs_notice").stdout + _bash(workdir, "ha_envs_notice").stderr == ""

    os.utime(_root(workdir) / ".refreshed", (0, 0))
    (workdir / "hacs.json").write_text('{"homeassistant": "2026.12.0"}\n', encoding="utf-8")
    result = _bash(workdir, "ha_envs_notice")
    output = result.stdout + result.stderr

    assert "last refreshed over 7 days ago" in output
    assert "hacs.json asks for 2026.12" in output
