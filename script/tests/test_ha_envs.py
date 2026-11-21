"""Tests for script/.lib/ha_envs.sh, with stubbed version resolution and venv builds."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

LIB = Path(__file__).parents[1] / ".lib"
STUBS = """
target_ha_version() { local -n _r="$1"; _r="$STUB_MINIMUM"; }
resolve_ha_version() {
    local -n _r="$1"
    case "$2" in latest) _r="$STUB_LATEST" ;; beta) _r="$STUB_BETA" ;; *) _r="$2" ;; esac
}
ha_envs_create_venv() { mkdir -p "$1/bin" "$1/lib"; echo "home = stub" >"$1/pyvenv.cfg"; touch "$1/bin/activate"; }
ha_envs_install() {
    [[ " ${STUB_FAIL:-} " == *" $2 "* ]] && return 1
    echo "$2" >>"$1/installs"
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
            *(f"source {LIB / name}" for name in ("output.sh", "ha_envs.sh")),
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
def test_an_unchanged_environment_is_not_installed_again(workdir: Path) -> None:
    """A refresh skips the install when neither the version nor a requirements file changed."""
    _bash(workdir, "ha_envs_refresh minimum; ha_envs_refresh minimum")
    installs = _root(workdir) / "versions" / "2026.11.2" / "installs"
    assert installs.read_text(encoding="utf-8").splitlines() == ["2026.11.2"]

    (workdir / "requirements_test.txt").write_text("pytest-homeassistant==2026.11.2\n", encoding="utf-8")
    _bash(workdir, "ha_envs_refresh minimum")

    assert installs.read_text(encoding="utf-8").splitlines() == ["2026.11.2", "2026.11.2"]


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
    assert _bash(workdir, "ha_current_slot").stdout == "beta"


@pytest.mark.unit
def test_use_refuses_a_slot_that_is_not_installed(workdir: Path) -> None:
    """Switching to a missing slot says how to add it and leaves the active one alone."""
    _bash(workdir, "ha_envs_refresh minimum; ha_envs_use minimum")

    result = _bash(workdir, "ha_envs_use latest")

    assert result.returncode == 1
    assert "script/ha-env add latest" in result.stdout + result.stderr
    assert _bash(workdir, "ha_current_slot").stdout == "minimum"


@pytest.mark.unit
def test_remove_keeps_minimum_and_the_active_slot(workdir: Path) -> None:
    """Minimum and the active slot cannot be removed; another slot can, and its venv goes with the next prune."""
    _bash(workdir, "for s in minimum latest beta; do ha_envs_refresh $s; done; ha_envs_use latest")

    assert _bash(workdir, "ha_envs_remove minimum").returncode == 1
    assert _bash(workdir, "ha_envs_remove latest").returncode == 1
    result = _bash(workdir, "ha_envs_remove beta; ha_envs_prune")

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (_root(workdir) / "slots").iterdir()) == ["latest", "minimum"]
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
def test_notice_names_a_stale_latest_or_beta_and_a_minimum_off_the_hacs_release(workdir: Path) -> None:
    """Both notices need no network; a fresh beta, an old minimum and the hacs.json release print nothing."""
    _bash(workdir, "for s in minimum beta; do ha_envs_refresh $s; done")
    slots = _root(workdir) / "slots"
    os.utime(slots / "minimum", (0, 0), follow_symlinks=False)
    result = _bash(workdir, "ha_envs_notice")
    assert result.stdout + result.stderr == ""

    os.utime(slots / "beta", (0, 0), follow_symlinks=False)
    (workdir / "hacs.json").write_text('{"homeassistant": "2026.12.0"}\n', encoding="utf-8")
    result = _bash(workdir, "ha_envs_notice")
    output = result.stdout + result.stderr

    assert "beta (2026.12.0b1) was last refreshed over 7 days ago" in output
    assert "minimum (" not in output
    assert "hacs.json asks for 2026.12" in output

    _bash(workdir, "ha_envs_refresh beta")
    assert "beta (" not in _bash(workdir, "ha_envs_notice").stderr


def _config(workdir: Path, ran: str) -> None:
    """A config/ last run by Home Assistant `ran`, with a little state of its own."""
    (workdir / "config" / ".storage").mkdir(parents=True)
    (workdir / "config" / ".storage" / "core.config_entries").write_text("{}\n", encoding="utf-8")
    (workdir / "config" / ".HA_VERSION").write_text(f"{ran}\n", encoding="utf-8")
    (workdir / "config" / "configuration.yaml").write_text("default_config:\n", encoding="utf-8")


@pytest.mark.unit
def test_a_new_config_dir_shares_files_and_starts_from_the_minimum_state(workdir: Path) -> None:
    """A newer environment links the shared files and copies config/'s state, which it can migrate forward."""
    _config(workdir, "2026.11.2")
    beta = workdir / ".local" / "ha-config" / "beta"

    result = _bash(workdir, f"ha_envs_prepare_config {beta} 2026.12.0b1")

    assert result.returncode == 0, result.stderr
    assert (beta / "configuration.yaml").is_symlink()
    assert (beta / "configuration.yaml").read_text(encoding="utf-8") == "default_config:\n"
    assert not (beta / ".storage").is_symlink()
    assert (beta / ".storage" / "core.config_entries").is_file()


@pytest.mark.unit
def test_an_older_environment_starts_with_empty_state(workdir: Path) -> None:
    """config/'s state is never handed to a Home Assistant older than the one that last wrote it."""
    _config(workdir, "2026.11.2")
    beta = workdir / ".local" / "ha-config" / "beta"

    result = _bash(workdir, f"ha_envs_prepare_config {beta} 2026.11.0b6")

    assert result.returncode == 0, result.stderr
    assert (beta / "configuration.yaml").is_symlink()
    assert not (beta / ".storage").exists()


@pytest.mark.unit
def test_an_existing_config_dir_keeps_its_own_state(workdir: Path) -> None:
    """Only a new config directory starts from config/; one with state of its own is left alone."""
    _config(workdir, "2026.11.2")
    beta = workdir / ".local" / "ha-config" / "beta"
    (beta / ".storage").mkdir(parents=True)
    (beta / ".storage" / "own").write_text("mine\n", encoding="utf-8")

    _bash(workdir, f"ha_envs_prepare_config {beta} 2026.12.0b1")

    assert sorted(path.name for path in (beta / ".storage").iterdir()) == ["own"]


@pytest.mark.unit
def test_the_guard_moves_aside_state_a_newer_version_wrote(workdir: Path) -> None:
    """State migrated by a newer Home Assistant is kept as a backup instead of breaking an older start."""
    _config(workdir, "2026.12.0")
    (workdir / "config" / "home-assistant_v2.db").write_text("db\n", encoding="utf-8")

    result = _bash(workdir, "ha_envs_guard_config config 2026.11.2; ha_envs_guard_config config 2026.12.0")

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (workdir / "config").iterdir() if ".bak" in path.name) == [
        ".storage.2026.12.0.bak",
        "home-assistant_v2.db.2026.12.0.bak",
    ]
    assert not (workdir / "config" / ".storage").exists()


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_the_prompt_names_the_active_environment_and_follows_a_switch(tmp_path: Path, shell: str) -> None:
    """Before each prompt the hook renews a stale activation and shows the slot and version now active."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    root = tmp_path / "root"
    for version in ("2026.11.2", "2026.12.0b1"):
        (root / "versions" / version / "bin").mkdir(parents=True)
        (root / "versions" / version / ".ha-version").write_text(f"{version}\n", encoding="utf-8")
        (root / "versions" / version / "bin" / "activate").write_text(
            f'VIRTUAL_ENV="{root}/versions/{version}"; export VIRTUAL_ENV\n', encoding="utf-8"
        )
    (root / "slots").mkdir()
    (root / "slots" / "minimum").symlink_to("../versions/2026.11.2")
    (root / "slots" / "beta").symlink_to("../versions/2026.12.0b1")
    (root / "current").symlink_to("slots/minimum")
    (root / "bin").symlink_to("current/bin")
    (root / ".switched").write_text("minimum\tbeta\tagent (claude-code)\t14:03\n", encoding="utf-8")
    script = (
        f"PS1='$ '; source {LIB / 'ha_env_prompt.sh'}; _ha_env_prompt; echo \"$PS1|${{VIRTUAL_ENV##*/}}\"; "
        f'ln -sfn slots/beta {root}/current; _ha_env_prompt; echo "$PS1|${{VIRTUAL_ENV##*/}}"'
    )
    env = {
        **os.environ,
        "HA_ENV_ROOT": str(root),
        "VIRTUAL_ENV": f"{root}/versions/2026.11.2",
        "WORKSPACE_ROOT": str(LIB.parents[1]),
    }

    result = subprocess.run([shell, "-c", script], env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["(ha-minimum 2026.11.2) $ |2026.11.2", "(ha-beta 2026.12.0b1) $ |2026.12.0b1"]
    assert "switched: minimum → beta (by agent (claude-code) at 14:03)" in result.stderr


PYPI = (
    '{"releases": {"2026.11.2": [{"requires_python": ">=3.14.2"}], "2026.12.0b1": [{"requires_python": ">=3.15.0"}]}}'
)


@pytest.mark.unit
def test_each_environment_gets_the_python_its_release_asks_for(workdir: Path) -> None:
    """The lower bound of requires-python picks the interpreter; downloads land beside the venvs."""
    script = f"""
source {LIB / "ha_envs.sh"}
_PYPI_JSON_CACHE='{PYPI}'
uv() {{ echo "UV_PYTHON_INSTALL_DIR=$UV_PYTHON_INSTALL_DIR $*"; }}
ha_envs_create_venv "$PWD/.local/ha-venv/versions/2026.12.0b1" 2026.12.0b1
ha_envs_create_venv "$PWD/.local/ha-venv/versions/2099.1.0" 2099.1.0
"""
    result = _bash(workdir, script)

    assert result.returncode == 0, result.stderr
    with_python, without = [line for line in result.stdout.splitlines() if line.startswith("UV_PYTHON_INSTALL_DIR")]
    assert with_python.startswith(f"UV_PYTHON_INSTALL_DIR={_root(workdir)}/python venv")
    assert "--python-preference only-managed --python 3.15" in with_python
    assert "--python-preference only-managed" in without
    assert "--python 3" not in without


@pytest.mark.unit
def test_prune_drops_downloaded_pythons_no_environment_uses(workdir: Path) -> None:
    """A downloaded Python stays while a venv's home points at it, through uv's minor-version link."""
    python = _root(workdir) / "python"
    for build in ("3.15.2", "3.16.0"):
        (python / f"cpython-{build}-linux").mkdir(parents=True)
        (python / f"cpython-{build[:4]}-linux").symlink_to(python / f"cpython-{build}-linux")
    _bash(workdir, "ha_envs_refresh beta")
    cfg = _root(workdir) / "versions" / "2026.12.0b1" / "pyvenv.cfg"
    cfg.write_text(f"home = {python}/cpython-3.15-linux/bin\n", encoding="utf-8")

    result = _bash(workdir, "ha_envs_prune")

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in python.iterdir()) == ["cpython-3.15-linux", "cpython-3.15.2-linux"]


@pytest.mark.unit
def test_uv_keeps_its_hardlinks_where_cache_and_venvs_share_a_filesystem(tmp_path: Path) -> None:
    """Only a hardlink-hostile setup gets a link mode; on one filesystem uv's own default stays, and no probe remains."""
    (tmp_path / "cache").mkdir()
    (tmp_path / "venv").mkdir()

    result = _bash(tmp_path, f"ha_envs_link_mode {tmp_path / 'cache'} {tmp_path / 'venv'} || echo default")

    assert result.stdout.strip() == "default"
    assert not [path for path in tmp_path.rglob("*") if "probe" in path.name]
