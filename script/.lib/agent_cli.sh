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
#   AGENT_MODEL  model passed to the CLI; unset leaves the CLI's own default
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

# _agent_signed_in NAME BIN: 0 when signed in, 1 when not, 2 when the CLI cannot tell without sending a request.
# Every check is local and bounded, so a CLI that waits for input cannot hang the caller.
_agent_signed_in() {
    local out
    case "$1" in
    claude)
        [[ -n "${ANTHROPIC_API_KEY:-}" ]] && return 0
        timeout 20 "$2" auth status --json </dev/null 2>/dev/null | jq -e '.loggedIn == true' >/dev/null 2>&1
        ;;
    codex)
        [[ -n "${CODEX_API_KEY:-}${OPENAI_API_KEY:-}" ]] && return 0
        timeout 20 "$2" login status </dev/null >/dev/null 2>&1
        ;;
    opencode)
        out="$(timeout 20 "$2" auth list </dev/null 2>/dev/null)" || return 1
        [[ -n "$out" && "$out" != *"No authenticated"* ]]
        ;;
    copilot)
        [[ -n "${COPILOT_GITHUB_TOKEN:-}${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]] && return 0
        return 2
        ;;
    esac
}

# agent_resolve [--any]: set AGENT_NAME and AGENT_BIN, or fail saying what is missing.
#
# AGENT_CLI names one CLI, which must be installed and, unless --any, not known to be signed out. Otherwise, in order:
# the CLI of the agent session this runs in, then the first CLI that is signed in, then one that cannot tell. --any
# takes the first installed CLI without asking: an interactive session lets the user sign in there.
agent_resolve() {
    local any="" name bin status unknown="" installed=()
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
        AGENT_NAME="$AGENT_CLI"
        AGENT_BIN="$bin"
        return 0
    fi

    if [[ -n "${CLAUDECODE:-}" ]] && bin="$(_agent_bin claude)" && [[ -n "$bin" ]]; then
        AGENT_NAME=claude
        AGENT_BIN="$bin"
        return 0
    fi

    for name in "${AGENT_CLIS[@]}"; do
        bin="$(_agent_bin "$name")"
        [[ -n "$bin" ]] || continue
        installed+=("$name")
        if [[ -n "$any" ]]; then
            AGENT_NAME="$name"
            AGENT_BIN="$bin"
            return 0
        fi
        status=0
        _agent_signed_in "$name" "$bin" || status=$?
        if [[ $status -eq 0 ]]; then
            AGENT_NAME="$name"
            AGENT_BIN="$bin"
            return 0
        fi
        [[ $status -eq 2 && -z "$unknown" ]] && unknown="$name"
    done

    if [[ -n "$unknown" ]]; then
        AGENT_NAME="$unknown"
        AGENT_BIN="$(_agent_bin "$unknown")"
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
agent_prompt() {
    local prompt_file="$1" model=() answer status=0
    [[ -n "${AGENT_MODEL:-}" ]] && model=(--model "$AGENT_MODEL")
    case "$AGENT_NAME" in
    claude)
        "$AGENT_BIN" --print --tools "" "${model[@]}" <"$prompt_file"
        ;;
    codex)
        answer="$(mktemp)"
        "$AGENT_BIN" exec --sandbox read-only --skip-git-repo-check "${model[@]}" \
            --output-last-message "$answer" - <"$prompt_file" >/dev/null || status=$?
        [[ $status -eq 0 ]] && cat "$answer"
        rm -f "$answer"
        return "$status"
        ;;
    copilot)
        "$AGENT_BIN" --silent --deny-tool='write' --deny-tool='shell' "${model[@]}" <"$prompt_file"
        ;;
    opencode)
        "$AGENT_BIN" run --agent plan --archived "${model[@]}" --file "$prompt_file" \
            "Follow the instructions in the attached file and reply with nothing else."
        ;;
    esac
}

# agent_session: replace the shell with an interactive session of the chosen CLI.
agent_session() {
    local model=()
    [[ -n "${AGENT_MODEL:-}" ]] && model=(--model "$AGENT_MODEL")
    exec "$AGENT_BIN" "${model[@]}"
}
