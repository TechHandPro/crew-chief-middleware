# x MCP server

MCP tools for **X API Posts (curated)** (2), generated from an OpenAPI document by
openapi-to-mcp 0.1.0 (crew-chief-middleware).

- Base URL: `https://api.x.com`
- Authentication: `bearer` (credentials from environment variables only)
- Tools: 4

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in credentials, keep it out of git
set -a && . ./.env && set +a
python server.py          # speaks MCP over stdio
```

The process reads MCP JSON-RPC on stdin and writes it on stdout, so it looks idle
when you start it by hand. Logs go to stderr.

## Connect an MCP client

Copy `mcp.example.json` into your client config (Cursor: `~/.cursor/mcp.json`, or
`.cursor/mcp.json` in a project), replace the placeholder path with the absolute
path to `server.py`, and provide credentials the way your client supports —
inherited environment, its `env` block, or a secret manager. Do not commit a
config file containing real credentials; `mcp.json` is git-ignored here.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `X_API_TOKEN` | bearer token (or a pre-obtained OAuth2 access token) |
| `X_BASE_URL` | override the API base URL |
| `X_READ_ONLY` | expose only non-mutating tools |
| `X_TIMEOUT_SECONDS` | per-request timeout (default 30) |
| `X_MAX_RESPONSE_BYTES` | response cap before truncation (default 100000) |
| `X_MAX_RETRIES` | retries for idempotent requests on 429/502/503/504 (default 2) |
| `X_ALLOW_INSECURE_HTTP` | allow plaintext http to a non-loopback host |
| `X_LOG_LEVEL` | stderr log level (default WARNING) |

## Tools

| Tool | Method | Path | Read-only |
| --- | --- | --- | --- |
| `get_me` | GET | `/2/users/me` | yes |
| `get_post` | GET | `/2/tweets/{id}` | yes |
| `create_post` | POST | `/2/tweets` | no |
| `upload_media` | POST | `/2/media/upload` | no |

## Layout

| Path | Role |
| --- | --- |
| `tools.json` | generated tool manifest: names, descriptions, JSON Schemas, HTTP bindings |
| `server.py` | entry point, plus the seams for hand-written tools |
| `mcp_runtime/` | vendored runtime: manifest loading, env config, auth, HTTP, MCP wiring |
| `.env.example` | every environment variable this server reads |
| `Dockerfile` | container image (stdio today, HTTP transport later) |

Regenerating with `openapi_to_mcp generate --force` rewrites `tools.json`,
`mcp_runtime/`, and this README. Keep hand-written tools in `server.py`.
