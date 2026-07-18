#!/bin/sh
set -eu

storage_dir="${STORAGE_DIR:-/data/storage}"

case "$storage_dir" in
  /*) ;;
  *)
    echo "STORAGE_DIR must be absolute: $storage_dir" >&2
    exit 64
    ;;
esac

# Railway mounts volumes as root. Create only the application-owned child
# directory, then drop privileges before running migrations or the web server.
install -d -m 0750 -o guardian -g guardian "$storage_dir"

exec gosu guardian "$@"
