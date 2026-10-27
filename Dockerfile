FROM postgres:17-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && command -v psql \
    && command -v pgbench \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
