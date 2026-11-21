# shellcheck shell=bash
# Shared by output.sh and the interactive prompt hook, so it depends on nothing else.

# ha_env_renew ROOT — re-activate a shell whose VIRTUAL_ENV still names a version `script/ha-env use` left behind.
ha_env_renew() {
    local root="$1"
    [[ -n $root && -L $root/current && ${VIRTUAL_ENV:-} == */versions/* && ! ${VIRTUAL_ENV:-} -ef $root/current ]] ||
        return 0
    # shellcheck source=/dev/null
    source "$root/bin/activate"
}
