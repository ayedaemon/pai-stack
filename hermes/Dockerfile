FROM nousresearch/hermes-agent:latest

# Bake the board-wide kanban default_model support into the image so
# hermes/config.yaml: kanban.default_model is actually honoured.
# The base image bundles /opt/hermes/hermes_cli/ — we patch it in-place
# using the Python fallback script (the unified diff patch has format
# issues with multi-file diffs, so we skip `patch` entirely).
USER root
COPY apply-kanban-patch.py /tmp/apply-kanban-patch.py
RUN cd /opt/hermes \
  && python3 /tmp/apply-kanban-patch.py \
  && rm -f /tmp/apply-kanban-patch.py \
  && python3 -c "from hermes_cli.config_defaults import *; print('kanban patch verified: default_model in defaults')" \
  && python3 -c "assert 'default_model' in open('/opt/hermes/hermes_cli/kanban_db_dispatch.py').read(), 'patch not applied to kanban_db_dispatch.py'"

# Keep root — s6-overlay must start as root and remaps via HERMES_UID/HERMES_GID env.
# Do NOT set USER here (see docker logs: "container started with --user 1000 ... not supported").
# USER root is the default.
