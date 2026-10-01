# Reverse-Proxy Security Headers (Traefik / Nginx)

The admin console (`/radius/`) manages credentials and PKI material — serve it
behind HTTPS with hardening headers. RADIUS/UDP ports (1812/1813/3799) are
unaffected by these HTTP headers.

## Traefik (Docker labels, Coolify-compatible)

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.middlewares.radius-secure.headers.stsSeconds=31536000"
  - "traefik.http.middlewares.radius-secure.headers.stsIncludeSubdomains=true"
  - "traefik.http.middlewares.radius-secure.headers.contentTypeNosniff=true"
  - "traefik.http.middlewares.radius-secure.headers.frameDeny=true"
  - "traefik.http.middlewares.radius-secure.headers.referrerPolicy=no-referrer"
  - "traefik.http.routers.radius.middlewares=radius-secure"
```

## Nginx (server block for the API host)

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer" always;

location /radius/ {
    proxy_pass http://127.0.0.1:8090;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Notes:
- `X-Forwarded-*` matters: the API runs with `--proxy-headers`, so rate
  limits and audit logs record the real client IP instead of the proxy IP.
- `X-Frame-Options: DENY` blocks clickjacking of the admin console.
- Certificate expiry: check CA/server cert dates monthly —
  `openssl x509 -in /etc/freeradius/3.0/certs/ca.pem -noout -enddate`.
  Losing the CA volume means re-issuing every client certificate (see README
  Backup section); back it up with `scripts/backup.sh`.
