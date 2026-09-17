# Meta Graph Pages MCP (SOCIAL)

Curated OpenAPI for one Facebook Page, generated into
[`generated/meta_graph_mcp`](generated/meta_graph_mcp). SOCIAL / Grok Bot
talks to Graph through that server. This is not a marketplace plugin and not
the WhatsApp-only official `facebook/openapi` spec.

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

`--name meta_graph` sets the env prefix to `META_GRAPH`.

## Credentials (never commit, never chat)

The Page access token is a secret. SOCIAL must not ask for it in Slack/chat.

1. Orange-prompt Jeremiah (or the operator) for a **Page** access token with
   at least `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`,
   and `read_insights`. Add `pages_manage_posts` / `pages_manage_engagement`
   only when writes will be enabled.
2. Store it in the TNT vault (platform org). Do not write it into git, `tools.json`,
   `.env` committed files, or `mcp.json` in the repo.
3. Inject it at runtime as `META_GRAPH_API_TOKEN`.

Start read-only:

```bash
export META_GRAPH_API_TOKEN='…from vault…'
export META_GRAPH_READ_ONLY=1
python examples/generated/meta_graph_mcp/server.py
```

`META_GRAPH_READ_ONLY=1` advertises only GET tools. Write tools stay in the
spec and in `tools.json`; unset the flag when SOCIAL is allowed to post.

Optional: `META_GRAPH_BASE_URL=https://graph.facebook.com/v26.0` if you pin a
newer Graph version without regenerating. Default in the spec is v24.0.

## Connect SOCIAL / Grok Bot

Same stdio contract as the tickets example. Point the host at
`examples/generated/meta_graph_mcp/server.py` with an absolute path and pass
env from the vault:

```json
{
  "mcpServers": {
    "meta_graph": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/examples/generated/meta_graph_mcp/server.py"],
      "env": {
        "META_GRAPH_API_TOKEN": "…injected from TNT vault…",
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
