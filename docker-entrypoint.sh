#!/bin/sh
# Drop root after fixing named-volume ownership so /app/data is writable as tca.
set -eu
if [ "$(id -u)" = 0 ]; then
  mkdir -p /app/data
  chown -R tca:tca /app/data
  exec setpriv --reuid=tca --regid=tca --init-groups -- "$@"
fi
exec "$@"
