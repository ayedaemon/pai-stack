#!/bin/sh
# Hermes entrypoint wrapper: syncs config.yaml from host, then delegates to real entrypoint
cp /tmp/config.yaml.host /opt/hermes/data/config.yaml
exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
