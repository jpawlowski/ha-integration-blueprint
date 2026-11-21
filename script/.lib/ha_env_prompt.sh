# shellcheck shell=bash
# Prompt hook for interactive bash and zsh in the dev container: the active Home Assistant environment, kept current.

HA_ENV_ROOT="${HA_ENV_ROOT:-$HOME/ha-venv}"
# shellcheck source=script/.lib/ha_env_renew.sh
[ -n "${WORKSPACE_ROOT:-}" ] && . "$WORKSPACE_ROOT/script/.lib/ha_env_renew.sh"
export VIRTUAL_ENV_DISABLE_PROMPT=1
_HA_ENV_BASE_PS1="$PS1"

_ha_env_prompt() {
    local link slot version="" to="" who="" at=""
    HA_ENV_PROMPT=""
    if link="$(readlink "$HA_ENV_ROOT/current" 2>/dev/null)"; then
        if command -v ha_env_renew >/dev/null; then
            ha_env_renew "$HA_ENV_ROOT"
        fi
        slot="${link##*/}"
        read -r version 2>/dev/null <"$HA_ENV_ROOT/current/.ha-version" || true
        HA_ENV_PROMPT="(ha-${slot}${version:+ $version}) "
        # Someone else switched — another terminal, a VS Code task or an agent: say so once, before this prompt.
        if [[ -n ${_HA_ENV_LAST:-} && $_HA_ENV_LAST != "$slot" ]]; then
            IFS=$'\t' read -r _ to who at 2>/dev/null <"$HA_ENV_ROOT/.switched" || true
            [[ $to == "$slot" ]] || who=""
            printf '\033[1;33m⚠ Home Assistant environment switched: %s → %s%s\033[0m\n' \
                "$_HA_ENV_LAST" "$slot" "${who:+ (by $who at $at)}" >&2
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
