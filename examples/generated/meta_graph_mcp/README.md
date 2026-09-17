# meta_graph MCP server

MCP tools for **Meta Graph Pages API (curated)** (24.0), generated from an OpenAPI document by
openapi-to-mcp 0.1.0 (crew-chief-middleware).

- Base URL: `https://graph.facebook.com/v24.0`
- Authentication: `bearer` (credentials from environment variables only)
- Tools: 19

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
| `META_GRAPH_API_TOKEN` | bearer token (or a pre-obtained OAuth2 access token) |
| `META_GRAPH_BASE_URL` | override the API base URL |
| `META_GRAPH_READ_ONLY` | expose only non-mutating tools |
| `META_GRAPH_TIMEOUT_SECONDS` | per-request timeout (default 30) |
| `META_GRAPH_MAX_RESPONSE_BYTES` | response cap before truncation (default 100000) |
| `META_GRAPH_MAX_RETRIES` | retries for idempotent requests on 429/502/503/504 (default 2) |
| `META_GRAPH_ALLOW_INSECURE_HTTP` | allow plaintext http to a non-loopback host |
| `META_GRAPH_LOG_LEVEL` | stderr log level (default WARNING) |

## Tools

| Tool | Method | Path | Read-only |
| --- | --- | --- | --- |
| `get_current_page` | GET | `/me` | yes |
| `list_managed_pages` | GET | `/me/accounts` | yes |
| `get_page` | GET | `/{page-id}` | yes |
| `list_page_feed` | GET | `/{page-id}/feed` | yes |
| `create_page_post` | POST | `/{page-id}/feed` | no |
| `list_page_posts` | GET | `/{page-id}/posts` | yes |
| `get_post` | GET | `/{post-id}` | yes |
| `list_post_comments` | GET | `/{post-id}/comments` | yes |
| `create_post_comment` | POST | `/{post-id}/comments` | no |
| `list_post_likes` | GET | `/{post-id}/likes` | yes |
| `get_comment` | GET | `/{comment-id}` | yes |
| `list_comment_replies` | GET | `/{comment-id}/comments` | yes |
| `reply_to_comment` | POST | `/{comment-id}/comments` | no |
| `list_page_insights` | GET | `/{page-id}/insights` | yes |
| `list_post_insights` | GET | `/{post-id}/insights` | yes |
| `list_page_photos` | GET | `/{page-id}/photos` | yes |
| `publish_page_photo` | POST | `/{page-id}/photos` | no |
| `list_page_videos` | GET | `/{page-id}/videos` | yes |
| `publish_page_video` | POST | `/{page-id}/videos` | no |

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
