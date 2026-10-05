#!/usr/bin/env bash
# Run ONE command with an environment file loaded - safely, without executing the file as shell.
#
#   scripts/with-env.sh ENV_FILE COMMAND [ARGS...]
#
# Why this exists: the production env files (deploy/env/*.example) are read by systemd as
# `EnvironmentFile=` for the services, but operators and the web build also need them. Sourcing such
# a file with `.` would execute it (a `&` or `;` in a DATABASE_URL would break or run something).
# This loader reads plain `KEY=VALUE` lines only, takes the value LITERALLY (no quotes, no
# expansion - the same rule as the templates) and then `exec`s the command. Nothing is printed
# except errors, and an error never echoes a line (it might be a secret).
#
# Exit codes: 2 = usage / unreadable file / malformed line; otherwise the command's own.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: with-env.sh ENV_FILE COMMAND [ARGS...]" >&2
  exit 2
fi

env_file=$1
shift

if [[ ! -f $env_file || ! -r $env_file ]]; then
  echo "with-env.sh: cannot read env file: ${env_file}" >&2
  exit 2
fi

line_no=0
while IFS= read -r line || [[ -n $line ]]; do
  line_no=$((line_no + 1))
  line=${line%$'\r'}
  if [[ $line =~ ^[[:space:]]*(#.*)?$ ]]; then
    continue
  fi
  if [[ ! $line =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
    echo "with-env.sh: ${env_file}:${line_no}: expected KEY=VALUE (line not shown)" >&2
    exit 2
  fi
  export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
done < "$env_file"

exec "$@"
