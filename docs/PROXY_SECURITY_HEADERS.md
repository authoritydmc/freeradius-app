# Reverse Proxy Security Headers & Hardening Guide

When exposing **RajLabs FreeRADIUS** behind a reverse proxy (Traefik, Nginx, Caddy, Cloudflare), configure standard HTTP security headers to protect against clickjacking, MIME sniffing, and downgrade attacks.

---

## 1. Traefik Middleware (Coolify & Standalone)

Add a Traefik middleware to attach security headers to your frontend routes:

```yaml
http:
  middlewares:
    radius-security-headers:
      headers:
        # Prevent Clickjacking on admin UI
        customFrameOptionsValue: "SAMEORIGIN"
        contentSecurityPolicy: "frame-ancestors 'self';"
        # Prevent MIME-type sniffing
        contentTypeNosniff: true
        # Prevent XSS reflections
        browserXssFilter: true
        # HTTP Strict Transport Security (HSTS)
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        # Referrer Policy
        referrerPolicy: "strict-origin-when-cross-origin"
```

In your `docker-compose.yml` router labels:
```yaml
labels:
  - "traefik.http.routers.radius-web.middlewares=radius-security-headers"
```

---

## 2. Nginx Reverse Proxy Configuration

```nginx
server {
    server_name wifi.rajlabs.in;
    listen 443 ssl http2;

    ssl_certificate /etc/letsencrypt/live/wifi.rajlabs.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/wifi.rajlabs.in/privkey.pem;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header Content-Security-Policy "frame-ancestors 'self';" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 3. Real Client IP Extraction

The API runs with `--proxy-headers --forwarded-allow-ips='*'`, and parses real client IPs in order of precedence:
1. `CF-Connecting-IP` (Cloudflare)
2. `X-Forwarded-For` (Traefik / Nginx)
3. `X-Real-IP`
4. Socket connection address

This ensures accurate rate limiting, login failure tracking, and audit logging.
