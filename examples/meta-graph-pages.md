# Meta Graph Pages example

Curated OpenAPI for one Facebook Page, generated into
[`generated/meta_graph_mcp`](generated/meta_graph_mcp). This is one vendor
example of what the generator produces — not a marketplace plugin, and not
the WhatsApp-only official `facebook/openapi` spec. Any other OpenAPI 3
document can follow the same generate → env-token → `*_READ_ONLY=1` path.

## What it covers

| Need | Tools |
| --- | --- |
| Page metadata | `get_current_page`, `get_page`, `list_managed_pages` |
| Posts | `list_page_feed`, `list_page_posts`, `get_post`, `create_page_post` |
| Comments / engagement | `list_post_comments`, `get_comment`, `list_comment_replies`, `list_post_likes`, writes `create_post_comment` / `reply_to_comment` |
| Insights | `list_page_insights`, `list_post_insights` |
| Photos / videos | list tools plus URL publish (`publish_page_photo`, `publish_page_video`) |

Out of scope here: Messenger, Ads, Reels rupload, Instagram, X/Twitter.

## Generate (keep the committed example current)

```bash
openapi_to_mcp list-tools \
  --spec examples/meta-graph-pages-openapi.yaml \
  --name meta_graph \
  --overrides examples/meta-graph-pages-overrides.yaml

openapi_to_mcp generate \
  --spec examples/meta-graph-pages-openapi.yaml \
  --out examples/generated/meta_graph_mcp \
  --name meta_graph \
  --overrides examples/meta-graph-pages-overrides.yaml \
  --force
```

`make example` regenerates this server and the tickets sample.

The discover → generate → fail-closed `READ_ONLY` smoke → seat a **non-prod**
agent loop is documented in [`docs/FACTORY_LOOP.md`](../docs/FACTORY_LOOP.md).
`make factory` wraps `list-tools`, `generate`, and `scripts/factory_smoke.py`
for these files.

`--name meta_graph` sets the env prefix to `META_GRAPH`.

## Credentials (never commit, never chat)

The Page access token is a secret. Load it from the environment or your
host's secret manager — never from chat, git, or a committed file.

1. Obtain a **Page** access token with at least `pages_show_list`,
   `pages_read_engagement`, `pages_read_user_content`, and `read_insights`.
   Add `pages_manage_posts` / `pages_manage_engagement` only when writes will
   be enabled.
2. Store it in whatever secret store your host uses. Do not write it into
   git, `tools.json`, committed `.env` files, or `mcp.json` in the repo.
3. Inject it at runtime as `META_GRAPH_API_TOKEN`.

Start read-only:

```bash
export META_GRAPH_API_TOKEN='…from your secret manager…'
export META_GRAPH_READ_ONLY=1
python examples/generated/meta_graph_mcp/server.py
```

`META_GRAPH_READ_ONLY=1` advertises only GET tools. Write tools stay in the
spec and in `tools.json`; unset the flag when the agent is allowed to post.

Optional: `META_GRAPH_BASE_URL=https://graph.facebook.com/v26.0` if you pin a
newer Graph version without regenerating. Default in the spec is v24.0.

## Connect an MCP client

Same stdio contract as the tickets example. Point the host at
`examples/generated/meta_graph_mcp/server.py` with an absolute path and pass
the token in the child environment:

```json
{
  "mcpServers": {
    "meta_graph": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/examples/generated/meta_graph_mcp/server.py"],
      "env": {
        "META_GRAPH_API_TOKEN": "…injected from your secret manager…",
        "META_GRAPH_READ_ONLY": "1"
      }
    }
  }
}
```

First call: `get_current_page` to recover `page-id`. Do not request
`access_token` in `fields`.

## Permissions reminder

| Task | Typical Graph permissions |
| --- | --- |
| Read Page + feed + comments | `pages_show_list`, `pages_read_engagement`, `pages_read_user_content` |
| Insights | `read_insights` |
| Create posts / URL media | `pages_manage_posts` |
| Comment as the Page | `pages_manage_engagement` |

Photo and video publish here are URL-only so the generated runtime can send
form fields (the same shape Meta's curl examples use). Binary multipart and
`rupload.facebook.com` are omitted on purpose.

## Optional operator notes

Some crews keep tokens in an internal vault and issue them out of band
(never in chat). That is a host habit, not a requirement of this example or
of the generator.

If you follow that habit:

1. Prompt the operator out of band (sometimes called an orange-prompt) for a
   **Page** access token with the permissions above.
2. Store it in your vault. Do not write it into git, `tools.json`, committed
   `.env` files, or `mcp.json` in the repo.
3. Inject it at runtime as `META_GRAPH_API_TOKEN`.

One measured crew runbook for discover → generate → smoke lives in
[`docs/FACTORY_LOOP.md`](../docs/FACTORY_LOOP.md). Keep
`META_GRAPH_READ_ONLY=1` on any production Page-publishing host until a human
approves live writes.
