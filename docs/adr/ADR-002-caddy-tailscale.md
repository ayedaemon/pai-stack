# ADR-002: Caddy + Tailscale TLS for All Ingress

## Status
Accepted

## Context
Services need HTTPS from any user device without public IP or DNS purchase. Pi may be behind NAT. Options were Cloudflare Tunnel, Traefik + Let's Encrypt, or Tailscale.

## Decision
Build Caddy with `caddy-tailscale` `caddy/Dockerfile:4` (`github.com/tailscale/caddy-tailscale`), mount `/var/run/tailscale/tailscaled.sock:ro` `docker-compose.yaml:27`, and serve every service as `{$TAILSCALE_DOMAIN}:port { tls { get_certificate tailscale } }` `caddy/Caddyfile:5`. No public ports.

## Alternatives Considered
- **Cloudflare Tunnel** — great for public sharing, but ties to Cloudflare account and extra daemon; not needed for tailnet-only access.
- **Traefik + Let's Encrypt DNS-01** — requires DNS API keys and public DNS control; more config.
- **Tailscale Serve/Funnel directly** — viable, but Caddy gives uniform reverse_proxy rules in one `Caddyfile:9` and Docker-network routing.

## Consequences
- Positive: Zero public attack surface, MagicDNS `rpi.burro-smelt.ts.net` auto-certs, Tailscale IP `100.x` or LAN both work as `TARGET_HOST` `.env.example:4`.
- Negative: Access requires tailnet membership; sharing outside tailnet needs Funnel or separate proxy.

## Trade-offs
Privacy and zero-config TLS prioritized over public shareability. Funnel can be added later without changing services.
