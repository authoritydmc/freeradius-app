FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    freeradius \
    freeradius-postgresql \
    freeradius-utils \
    postgresql-client \
    python3 \
    python3-pip \
    python3-fastapi \
    python3-uvicorn \
    python3-pydantic \
    python3-psycopg2 \
    python3-jinja2 \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY config/ /app/config/
COPY api/ /app/api/
COPY scripts/ /app/scripts/

RUN chmod +x /app/scripts/*.sh

EXPOSE 1812/udp 1813/udp 3799/udp 8090/tcp

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
