---
name: cursor-shell-debugging
description: >-
  Shell debugging hygiene in Cursor agent sessions. Covers env variable
  persistence, token/credential handling, JSON parsing, and when to use
  existing data instead of live API calls. Use when debugging APIs, scripting
  multi-step shell workflows, or whenever a previous shell command's output
  needs to survive into the next call.
---

# Cursor Shell Debugging

## Env variables do not survive between Shell tool calls

Each Shell call is a fresh shell. Variables set in one call are gone in the next.

**Wrong:**
```bash
# Call 1
TOKEN=$(curl -s .../token | jq -r '.access_token')

# Call 2 — TOKEN is empty
curl -H "Authorization: Bearer $TOKEN" .../data
```

**Right — save to a file, read from it:**
```bash
# Call 1: fetch once, save
curl -s .../token -o /tmp/token.json

# Call 2: read from file
curl -H "Authorization: Bearer $(jq -r '.access_token' /tmp/token.json)" .../data
```

Use `/tmp/` for short-lived artifacts. Use descriptive names (`/tmp/ha-token.json`, not `/tmp/t`).

## Fetch credentials/tokens once — never re-fetch in subsequent calls

If a call needs auth, exchange for a token in the first call and write it to disk. All later calls read from disk. Never re-exchange unless the file is missing or stale.

```bash
# First call only
curl -s 'https://api.example.com/token' \
  -d 'grant_type=client_credentials&client_id=...' \
  -o /tmp/api-token.json

# All later calls
TOKEN=$(jq -r '.access_token' /tmp/api-token.json)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/data
```

## Use jq, not python3, for JSON in the shell

`jq` is faster to write, easier to read, and doesn't need escaping gymnastics.

```bash
# jq
jq '{status, count, items: (.result | length)}' /tmp/response.json
jq -r '.result[] | [.id, .channelName, (.source // "NULL")] | @tsv' /tmp/response.json

# python3 — only when jq can't do it (complex logic, cross-field computation)
python3 -c "import json; d=json.load(open('/tmp/response.json')); ..."
```

Pipe `@tsv` through `sort | uniq -c | sort -rn` to get frequency tables from any JSON array.

## Prefer stored data over live API calls

If the data is already in a database or file, query it there. Live API calls add:
- Auth complexity (tokens, scopes)
- Rate limit risk
- Network latency and timeouts
- Potential for incomplete results (pagination)

DynamoDB, ClickHouse, S3 — if the data was ingested, start there.

## Save large responses to files before inspecting

Don't pipe a big curl response directly into jq in the same call. Save first, inspect separately — you can re-run the inspection without re-hitting the API.

```bash
# Call 1: save
curl -s "https://api.example.com/data?limit=100" \
  -H "Authorization: Bearer $(jq -r '.access_token' /tmp/token.json)" \
  -o /tmp/data.json

# Call 2+: inspect repeatedly, no API hits
jq '.result | length' /tmp/data.json
jq -r '.result[] | [.id, .name] | @tsv' /tmp/data.json | sort | uniq -c
```

## Batch independent shell commands; keep dependent ones sequential

Multiple independent operations — run in one message with multiple Shell calls.
Sequential dependent operations — use `&&` or a single Shell call with explicit ordering.

Don't chain with `&&` when you want to inspect intermediate output — save to file instead.

## Check terminal files before re-running commands

The terminals folder contains existing output from running sessions. Read it before issuing a command you think might already have run. Avoids duplicate API calls and redundant work.
