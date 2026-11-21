# shellcheck shell=bash
# ha_env_prompt.sh: Show the active Home Assistant environment in the prompt, and follow `script/ha-env use`.
#
# Sourced by interactive bash and zsh in the dev container, from .devcontainer/.bashrc and .zshrc, which
# .devcontainer/setup-shell.sh installs. Before every prompt it renews an activation that still names an
# environment the user switched away from, so terminals opened earlier follow the switch.

HA_ENV_ROOT="${HA_ENV_ROOT:-$HOME/ha-venv}"
export VIRTUAL_ENV_DISABLE_PROMPT=1
# The activation earlier in the rc file has already prefixed the prompt; start again from the one it saved.
if [[ -n ${_OLD_VIRTUAL_PS1+x} ]]; then
    PS1="$_OLD_VIRTUAL_PS1"
fi
_HA_ENV_BASE_PS1="$PS1"

_ha_env_prompt() {
    local root active slot version to who at
    HA_ENV_PROMPT=""
    if [[ -L $HA_ENV_ROOT/current ]]; then
        root="$(realpath -m "$HA_ENV_ROOT")"
        active="$(realpath -m "$HA_ENV_ROOT/current")"
        if [[ -n ${VIRTUAL_ENV:-} && $(realpath -m "$VIRTUAL_ENV") == "$root"/versions/* &&
        $(realpath -m "$VIRTUAL_ENV") != "$active" ]]; then
            # shellcheck source=/dev/null
            source "$HA_ENV_ROOT/bin/activate"
        fi
        slot="$(basename "$(readlink "$HA_ENV_ROOT/current")")"
        version="$(cat "$HA_ENV_ROOT/current/.ha-version" 2>/dev/null)"
        HA_ENV_PROMPT="(ha-${slot}${version:+ $version}) "
        # Someone else switched — another terminal, a VS Code task or an agent: say so once, before this prompt.
        if [[ -n ${_HA_ENV_LAST:-} && $_HA_ENV_LAST != "$slot" ]]; then
            IFS=$'\t' read -r _ to who at <"$HA_ENV_ROOT/.switched" 2>/dev/null || true
            if [[ ${to:-} == "$slot" && -n ${who:-} ]]; then
                printf '\033[1;33m⚠ Home Assistant environment switched: %s → %s (by %s at %s)\033[0m\n' \
                    "$_HA_ENV_LAST" "$slot" "$who" "$at" >&2
            else
                printf '\033[1;33m⚠ Home Assistant environment switched: %s → %s\033[0m\n' "$_HA_ENV_LAST" "$slot" >&2
            fi
        fi
        _HA_ENV_LAST="$slot"
    fi
    PS1="${HA_ENV_PROMPT}${_HA_ENV_BASE_PS1}"
}

if [[ -n ${ZSH_VERSION:-} ]]; then
    autoload -Uz add-zsh-hook
    add-zsh-hook precmd _ha_env_prompt
elif [[ ${PROMPT_COMMAND:-} != *_ha_env_prompt* ]]; then
    PROMPT_COMMAND="_ha_env_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
