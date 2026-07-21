FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 tca \
    && git config --system --add safe.directory '*'

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY perms/ perms/
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN pip install --no-cache-dir . \
    && mkdir -p /app/data \
    && chown -R tca:tca /app \
    && chmod +x /docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1

# Entrypoint runs as root briefly to chown the data volume, then drops to uid 1000.
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "telegram_cursor_agent.bot"]
