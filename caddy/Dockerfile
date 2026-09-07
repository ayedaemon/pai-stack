# Build Caddy with the Tailscale certificate module
FROM caddy:builder AS builder

RUN xcaddy build \
    --with github.com/tailscale/caddy-tailscale@latest

FROM caddy:latest
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
