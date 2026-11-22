#!/bin/bash
# Coding agent CLI library
# shellcheck disable=SC2034  # AGENT_NAME and AGENT_BIN are used by sourcing scripts
#
# Runs a one-shot prompt through whichever coding agent CLI is installed and signed in — Claude Code, Codex, GitHub
# Copilot or OpenCode, all four of which the dev container installs. The prompt gets no tools: everything the agent
# needs is in the prompt, and it only returns text.
#
# Variables read:
#   AGENT_CLI    claude, codex, copilot or opencode; unset or "auto" picks one (see agent_resolve)
#   AGENT_MODEL  model passed to the CLI; unset leaves the CLI's own default (for copilot: COPILOT_MODEL)
#
# Set after agent_resolve:
#   AGENT_NAME   the chosen CLI's name
#   AGENT_BIN    the command that runs it

AGENT_CLIS=(claude codex copilot opencode)

# _agent_bin NAME: print the command for one CLI, or nothing when it is not installed.
_agent_bin() {
    if [[ "$1" == copilot && -x "$PWD/node_modules/.bin/copilot" ]]; then
        echo "$PWD/node_modules/.bin/copilot"
    elif command -v "$1" >/dev/null 2>&1; then
        echo "$1"
    fi
}

# _agent_login NAME: print how to sign in to one CLI.
_agent_login() {
    case "$1" in
    claude) echo "run claude and type /login" ;;
    codex) echo "codex login" ;;
    copilot) echo "copilot login" ;;
    opencode) echo "opencode auth login" ;;
    esac
}

# _agent_has_key NAME: succeed when the environment holds a key the CLI signs in with — no process needed.
_agent_has_key() {
    case "$1" in
    claude) [[ -n "${ANTHROPIC_API_KEY:-}" ]] ;;
    codex) [[ -n "${CODEX_API_KEY:-}${OPENAI_API_KEY:-}" ]] ;;
    # GH_TOKEN and GITHUB_TOKEN are often set for gh or CI without Copilot access, so they prove nothing.
    copilot) [[ -n "${COPILOT_GITHUB_TOKEN:-}" ]] ;;
    *) return 1 ;;
    esac
}

# _agent_signed_in NAME BIN: 0 when signed in, 1 when not, 2 when the CLI cannot tell without sending a request.
# Every check is local and bounded, so a CLI that waits for input cannot hang the caller.
_agent_signed_in() {
    local out
    _agent_has_key "$1" && return 0
    case "$1" in
    claude)
        timeout 10 "$2" auth status --json </dev/null 2>/dev/null | jq -e '.loggedIn == true' >/dev/null 2>&1
        ;;
    codex)
        timeout 10 "$2" login status </dev/null >/dev/null 2>&1
        ;;
    opencode)
        out="$(timeout 10 "$2" auth list </dev/null 2>/dev/null)" || return 1
        [[ -n "$out" && "$out" != *"No authenticated"* ]]
        ;;
    copilot)
        return 2
        ;;
    esac
}

# _agent_session_cli: print the CLI of the agent session this runs in, as ha_actor in output.sh recognises it.
_agent_session_cli() {
    local agent="${AI_AGENT:-}"
    agent="${agent%%_*}"
    agent="$(printf '%s' "$agent" | tr '[:upper:]' '[:lower:]')"
    if [[ " ${AGENT_CLIS[*]} " == *" $agent "* ]]; then
        echo "$agent"
    elif [[ -n "${CLAUDECODE:-}" ]]; then
        echo claude
    fi
}

# _agent_use NAME BIN: make NAME the chosen CLI.
_agent_use() {
    AGENT_NAME="$1"
    AGENT_BIN="$2"
    if [[ "$1" == copilot && -z "${AGENT_MODEL:-}" ]]; then
        AGENT_MODEL="${COPILOT_MODEL:-}"
    fi
}

# agent_resolve [--any]: set AGENT_NAME and AGENT_BIN, or fail saying what is missing.
#
# AGENT_CLI names one CLI, which must be installed and, unless --any, not known to be signed out. Otherwise, in order:
# the CLI of the agent session this runs in, then the first CLI with a key in the environment, then the first that
# reports being signed in, then one that cannot tell. --any takes the first installed CLI without asking: an
# interactive session lets the user sign in there.
agent_resolve() {
    local any="" i name bin status unknown="" unknown_bin="" installed=() bins=()
    [[ "${1:-}" == --any ]] && any=1

    if [[ -n "${AGENT_CLI:-}" && "$AGENT_CLI" != auto ]]; then
        if [[ " ${AGENT_CLIS[*]} " != *" $AGENT_CLI "* ]]; then
            echo "AGENT_CLI=$AGENT_CLI is not one of: ${AGENT_CLIS[*]}" >&2
            return 1
        fi
        bin="$(_agent_bin "$AGENT_CLI")"
        if [[ -z "$bin" ]]; then
            echo "AGENT_CLI=$AGENT_CLI, but $AGENT_CLI is not installed" >&2
            return 1
        fi
        if [[ -z "$any" ]]; then
            status=0
            _agent_signed_in "$AGENT_CLI" "$bin" || status=$?
            if [[ $status -eq 1 ]]; then
                echo "AGENT_CLI=$AGENT_CLI, but it is not signed in — $(_agent_login "$AGENT_CLI")" >&2
                return 1
            fi
        fi
        _agent_use "$AGENT_CLI" "$bin"
        return 0
    fi

    name="$(_agent_session_cli)"
    if [[ -n "$name" ]] && bin="$(_agent_bin "$name")" && [[ -n "$bin" ]]; then
        _agent_use "$name" "$bin"
        return 0
    fi

    for name in "${AGENT_CLIS[@]}"; do
        bin="$(_agent_bin "$name")"
        [[ -n "$bin" ]] || continue
        if [[ -n "$any" ]] || _agent_has_key "$name"; then
            _agent_use "$name" "$bin"
            return 0
        fi
        installed+=("$name")
        bins+=("$bin")
    done

    for ((i = 0; i < ${#installed[@]}; i++)); do
        status=0
        _agent_signed_in "${installed[$i]}" "${bins[$i]}" || status=$?
        if [[ $status -eq 0 ]]; then
            _agent_use "${installed[$i]}" "${bins[$i]}"
            return 0
        fi
        if [[ $status -eq 2 && -z "$unknown" ]]; then
            unknown="${installed[$i]}"
            unknown_bin="${bins[$i]}"
        fi
    done

    if [[ -n "$unknown" ]]; then
        _agent_use "$unknown" "$unknown_bin"
        return 0
    fi
    if [[ ${#installed[@]} -eq 0 ]]; then
        echo "No coding agent CLI found — install one of: ${AGENT_CLIS[*]}" >&2
        return 1
    fi
    echo "No agent CLI is signed in. Sign in to one of them:" >&2
    for name in "${installed[@]}"; do
        echo "  $name: $(_agent_login "$name")" >&2
    done
    return 1
}

# agent_prompt FILE: send the prompt in FILE and print only the agent's answer.
#
# The CLI runs in an empty directory (Copilot, which would ask to trust it, with --no-custom-instructions instead), so
# it loads none of this repository's agent instructions or session hooks: the answer comes from the prompt alone.
agent_prompt() {
    local prompt_file work answer status=0
    prompt_file="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
    set --
    if [[ -n "${AGENT_MODEL:-}" ]]; then
        set -- --model "$AGENT_MODEL"
    fi
    work="$(mktemp -d)"
    case "$AGENT_NAME" in
    claude)
        (cd "$work" && "$AGENT_BIN" --print --tools "" "$@") <"$prompt_file" || status=$?
        ;;
    codex)
        answer="$work/answer.md"
        (cd "$work" && "$AGENT_BIN" exec --sandbox read-only --skip-git-repo-check "$@" \
            --output-last-message "$answer" -) <"$prompt_file" >/dev/null || status=$?
        if [[ $status -eq 0 ]]; then
            cat "$answer"
        fi
        ;;
    copilot)
        "$AGENT_BIN" --silent --no-custom-instructions --deny-tool='write' --deny-tool='shell' "$@" \
            <"$prompt_file" || status=$?
        ;;
    opencode)
        (cd "$work" && "$AGENT_BIN" run --agent plan --archived "$@" --file "$prompt_file" \
            "Follow the instructions in the attached file and reply with nothing else.") || status=$?
        ;;
    esac
    rm -rf "$work"
    return "$status"
}

# agent_session: replace the shell with an interactive session of the chosen CLI.
agent_session() {
    if [[ -n "${AGENT_MODEL:-}" ]]; then
        exec "$AGENT_BIN" --model "$AGENT_MODEL"
    fi
    exec "$AGENT_BIN"
}
