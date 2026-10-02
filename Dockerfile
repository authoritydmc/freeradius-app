FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
# All expiry math is UTC epoch (Python + FreeRADIUS `expiration` wall-time
# parse must agree). Pin TZ so host TZ can never skew Expiration checks.
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    freeradius \
    freeradius-postgresql \
    freeradius-utils \
    postgresql-client \
    python3 \
    python3-pip \
    procps \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api/requirements.txt /app/api/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/api/requirements.txt

COPY config/ /app/config/
COPY api/ /app/api/
COPY scripts/ /app/scripts/

RUN chmod +x /app/scripts/*.sh

EXPOSE 1812/udp 1813/udp 3799/udp 8090/tcp

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
