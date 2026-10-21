# Settings loader for the build scripts. Source it, then call: load_config [config-file]
#
# Applies defaults.env, then the config file (argument, or $CONFIG), then whatever was
# already set in the environment, and exports every setting. The list of settings is the
# list of keys in defaults.env.
#
#   docker_env_args   prints "-e KEY" for every setting, to hand them into a container

TOOLCHAINS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CONFIG_DEFAULTS="$TOOLCHAINS/pipeline/defaults.env"
CONFIG_KEYS=$(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' "$CONFIG_DEFAULTS")

load_config() {
    local file=${1:-${CONFIG:-}} key
    declare -A from_env
    for key in $CONFIG_KEYS; do
        if [ -n "${!key+set}" ]; then from_env[$key]=${!key}; fi
    done
    # shellcheck source=defaults.env
    source "$CONFIG_DEFAULTS"
    if [ -n "$file" ]; then
        [ -f "$file" ] || { echo "config file not found: $file" >&2; return 1; }
        source "$file"
    fi
    for key in "${!from_env[@]}"; do
        printf -v "$key" '%s' "${from_env[$key]}"
    done
    for key in $CONFIG_KEYS; do export "$key"; done
    export TOOLCHAINS
}

docker_env_args() {
    local key
    for key in $CONFIG_KEYS; do printf -- '-e %s ' "$key"; done
}
