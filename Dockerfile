FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY perms/ perms/

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "telegram_cursor_agent.bot"]
