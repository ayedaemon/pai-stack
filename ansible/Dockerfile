FROM python:3.11-slim

LABEL maintainer="pai-stack"
LABEL description="One-time containerized Ansible runner for pai-stack deployment"

# Install sshpass, openssh-client and prerequisites for password-based authentication
RUN apt-get update && apt-get install -y --no-install-recommends \
    sshpass \
    openssh-client \
    curl \
    gnupg \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install ansible and required python libraries
# (bcrypt is used directly to hash the Syncthing basic-auth password)
RUN pip install --no-cache-dir ansible-core ansible bcrypt

WORKDIR /workspace/ansible

# Set entrypoint to run ansible-playbook
ENTRYPOINT ["ansible-playbook"]
CMD ["playbook.yml", "--ask-pass", "--ask-become-pass"]
