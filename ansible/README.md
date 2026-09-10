# ansible/ — Deployment

Automated deployment of **Hermes Agent**, **CodeGraph**, and **Syncthing (host)** to a Raspberry Pi or any Linux server.

## What You Need

- `ansible-core` (`pip install ansible-core`)
- `sshpass` (`brew install hudochenkov/sshpass/sshpass` on macOS)
- SSH access to target

## Files

```
ansible/
├── playbook.yml              # Flat deployment playbook (all tasks, no roles)
├── group_vars/all.yml        # Configurable variables
├── inventory.ini             # Optional inventory file
├── templates/
│   ├── env.j2                # Target .env template
│   └── hermes/config.yaml.j2
└── Skills/                  # KB scaffold → ~/stack_root/Skills
```

## Local install (localhost)

```bash
ansible-playbook -i "localhost," -u $USER ansible/playbook.yml -K -k
```

## Remote install (common case)

```bash
ansible-playbook -i "${TARGET_HOST}," -u "${TARGET_USER}" ansible/playbook.yml \
  -e "@.env" -k -K
```

Or set `SSH_PASSWORD` and `BECOME_PASSWORD` in `.env` for zero-prompt deploys.

## What the Playbook Does

1. Installs Tailscale (optional, skipped if no `TAILSCALE_AUTH_KEY`)
2. Installs Docker via `get.docker.com`
3. Creates directories (`~/stack_root`, `~/stack_root/Skills`, `~/deployed-pai-stack`)
4. Clones pai-stack repo
5. Templates `.env` (auto-generates secrets if blank)
6. Templates hermes `config.yaml`
7. Seeds KB scaffold (`Skills/`, never overwrites existing)
8. Installs Syncthing host service (systemd, binds `0.0.0.0:8384`)
9. Builds & starts Docker containers
10. Displays access summary

## Variables

See `group_vars/all.yml` for all configurable variables. Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `tailscale_auth_key` | _(empty, skip Tailscale)_ | Auth key to join tailnet |
| `pai_stack_root` | `~/stack_root` | STACK_ROOT location |
| `pai_stack_dir` | `~/deployed-pai-stack` | Where repo is cloned |
| `syncthing_gui_user` | `admin` | Syncthing GUI username |

## Re-deploy

Re-running is safe. Existing `.env` secrets are preserved, `Skills/` scaffold is not overwritten, and Syncthing config is only patched if needed.
