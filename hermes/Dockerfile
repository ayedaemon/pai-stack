FROM nousresearch/hermes-agent:latest

USER root

# Install inotify-tools for fs-notifier (filesystem watcher)
RUN apt-get update && \
    apt-get install -y --no-install-recommends inotify-tools curl && \
    rm -rf /var/lib/apt/lists/*

# Patch kanban default_model support
COPY apply-kanban-patch.py /tmp/apply-kanban-patch.py
RUN cd /opt/hermes \
  && python3 /tmp/apply-kanban-patch.py \
  && rm -f /tmp/apply-kanban-patch.py \
  && python3 -c "from hermes_cli.config_defaults import *; print('kanban patch verified: default_model in defaults')" \
  && python3 -c "assert 'default_model' in open('/opt/hermes/hermes_cli/kanban_db_dispatch.py').read(), 'patch not applied to kanban_db_dispatch.py'"
