# X API Posts example

Curated OpenAPI for one X (Twitter) user — create/quote a Post and upload
images — generated into [`generated/x_mcp`](generated/x_mcp). This is one
vendor example of what the generator produces. It is **not** the Cursor
marketplace `user-X` plugin (that catalog is read + chat/bookmarks/webhooks
and has no create-post / media-upload tools). Any other OpenAPI 3 document
can follow the same generate → env-token → `*_READ_ONLY=1` path.

## What it covers

| Need | Tools |
| --- | --- |
| Identity | `get_me` (`GET /2/users/me`) |
| Lookup | `get_post` (`GET /2/tweets/{id}`) |
| Publish | `create_post` (`POST /2/tweets`) — text, `quote_tweet_id`, `media.media_ids`, `reply` |
| Images | `upload_media` (`POST /2/media/upload`) — JSON base64 one-shot |

Out of scope here: full X API, v1.1 HMAC, chunked `initialize`/`append`/`finalize`
(video), DMs, search, ads, multipart file bodies, and driving x.com in a browser.

## Why generate this (marketplace is read-only)

The marketplace X MCP plugin does not expose write tools. This repo's job is
the documented API: a small spec in, a stdio MCP server out. `create_post` and
`upload_media` are POST tools in `tools.json`; `X_READ_ONLY=1` hides them at
runtime until a human unsets the flag.

The runtime sends JSON (and form-urlencoded). It does **not** sign OAuth 1.0a
and does **not** send `multipart/form-data` files. X's one-shot image upload
accepts base64 in a JSON `media` field on `api.x.com`, so images fit the same
shape as the Meta Graph URL-publish example. Chunked video append does not.

## Generate (keep the committed example current)

```bash
openapi_to_mcp list-tools \
  --spec examples/x-api-openapi.yaml \
  --name x \
  --overrides examples/x-api-overrides.yaml

openapi_to_mcp generate \
  --spec examples/x-api-openapi.yaml \
  --out examples/generated/x_mcp \
  --name x \
  --overrides examples/x-api-overrides.yaml \
  --force
```

`make example` regenerates this server, the tickets sample, and Meta Graph.

`--name x` sets the env prefix to `X`.

The discover → generate → fail-closed `READ_ONLY` smoke → seat a **non-prod**
agent loop is documented in [`docs/FACTORY_LOOP.md`](../docs/FACTORY_LOOP.md).
Point `make factory` at these files when you want that dogfood path:

```bash
make factory \
  SPEC=examples/x-api-openapi.yaml \
  NAME=x \
  OUT=examples/generated/x_mcp \
  OVERRIDES=examples/x-api-overrides.yaml
```

Factory smoke is GET-only by default. It will call `get_me` and will not
publish. Keep `X_READ_ONLY=1` until a recorded write smoke is approved.

## Credentials (never commit, never chat)

The user access token is a secret. Load it from the environment or your
host's secret manager — never from chat, git, or a committed file.

1. Create an X developer app with **user** OAuth 2.0 (PKCE). Scopes:
   `tweet.read`, `tweet.write`, `users.read`, `media.write`, and usually
   `offline.access`. App-only / consumer-key bearers cannot call these writes.
2. Complete the user consent flow out of band and store the resulting
   **user** access token (and refresh token, if you rotate) in your secret
   store. Do not write it into git, `tools.json`, committed `.env` files, or
   `mcp.json` in the repo.
3. Inject it at runtime as `X_API_TOKEN`.

Start read-only:

```bash
export X_API_TOKEN='…from your secret manager…'
export X_READ_ONLY=1
python examples/generated/x_mcp/server.py
```

`X_READ_ONLY=1` advertises only GET tools. Write tools stay in the spec and
in `tools.json`; unset the flag when the agent is allowed to post.

Optional: `X_BASE_URL=https://api.x.com` (the spec default). Raise
`X_TIMEOUT_SECONDS` if a large base64 image upload needs more than 30s.

## Connect an MCP client

Same stdio contract as the tickets example. Point the host at
`examples/generated/x_mcp/server.py` with an absolute path and pass the
token in the child environment:

```json
{
  "mcpServers": {
    "x": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/examples/generated/x_mcp/server.py"],
      "env": {
        "X_API_TOKEN": "…injected from your secret manager…",
        "X_READ_ONLY": "1"
      }
    }
  }
}
```

First call: `get_me`. Then, to publish with an image:

1. `upload_media` with `media` (base64) and `media_category=tweet_image`.
2. `create_post` with `text` and `media.media_ids: ["<data.id>"]`.

To quote: `create_post` with `text` and `quote_tweet_id` (no `media`).

## Vendor limits the adapter cannot paper over

| Constraint | What to do |
| --- | --- |
| Marketplace X plugin has no write tools | Use this generated server, not the plugin, for publish. |
| `quote_tweet_id` + `media` are mutually exclusive | Quote with text, or reply with images (`reply.in_reply_to_tweet_id`). |
| Quote via API may require an entitled plan | If `create_post` with `quote_tweet_id` returns 403, check the X API tier. |
| OAuth 1.0a HMAC is unsupported here | Obtain an OAuth 2.0 **user** token; do not expect consumer key/secret signing. |
| Chunked video / multipart files | Out of scope (same reason Meta Graph omitted rupload). Images: JSON base64. |
| No token in the environment | Fail closed. Do not invent a parallel HTTP route on this host. |

If you cannot obtain a user-context token, or the X plan refuses quote/write,
the next sanctioned path is another MCP that already speaks X writes (for
example a multi-network publisher plugin), still with secrets in the host
environment — not a new first-party `/api/grok` route in this repo.

## Permissions reminder

| Task | Typical OAuth 2.0 user scopes |
| --- | --- |
| `get_me` | `users.read` |
| `get_post` | `tweet.read` |
| `create_post` | `tweet.write` (+ `tweet.read`) |
| `upload_media` | `media.write` |

## Optional operator notes

Some crews keep tokens in an internal vault and issue them out of band
(never in chat). That is a host habit, not a requirement of this example or
of the generator.

If you follow that habit:

1. Prompt the operator out of band (sometimes called an orange-prompt) for an
   X OAuth 2.0 **user** access token with the scopes above. Do not ask for
   it in Slack or a ticket comment.
2. Store it in your vault as `X_API_TOKEN` (same username/env name as Meta's
   `META_GRAPH_API_TOKEN` pattern). Do not write it into git, `tools.json`,
   committed `.env` files, or `mcp.json` in the repo. There is no X token in
   the vault until that paste lands — fail closed until it does.
3. Inject it at runtime as `X_API_TOKEN` on the SOCIAL (or scratch) MCP host
   that runs `examples/generated/x_mcp/server.py`. Keep `X_READ_ONLY=1` until
   a human approves live writes (`SMOKE_WRITES=1` plus a recorded non-prod
   POST). Leave the marketplace user-X plugin (id 49086599) installed for
   reads if useful; do not expect it to publish.

If a user-context token cannot be issued, the X plan refuses `tweet.write` /
`quote_tweet_id`, or you need a write that this runtime cannot send (chunked
video, multipart, OAuth 1.0a HMAC), the next sanctioned path is Zernio
(marketplace plugin 65143440) with secrets still in the vault — not a new
first-party `/api/grok` route in this repo.

One measured crew runbook for discover → generate → smoke lives in
[`docs/FACTORY_LOOP.md`](../docs/FACTORY_LOOP.md).
