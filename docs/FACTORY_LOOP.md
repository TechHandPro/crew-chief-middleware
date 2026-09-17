# MCP factory loop (TNT #330)

One **dogfood path**. This is not a factory product, a vendor registry, or an
Ops Console surface (those are #331 / #338). The loop that already worked for
Meta Graph Pages is the loop a crew repeats:

**discover → generate → READ_ONLY smoke → seat a non-prod agent**

Reference run (committed, no secrets):

- `examples/meta-graph-pages-openapi.yaml`
- `examples/meta-graph-pages-overrides.yaml`
- `examples/generated/meta_graph_mcp`
- operator notes: `examples/meta-graph-pages.md`

SLA: **hours, not weeks**, for this path on a known OpenAPI. A new vendor still
starts here — one spec, one generated server, one smoke — instead of a portal
click marathon.

## Kill-switch

`READ_ONLY` is the default. Factory smoke will not continue if writes are
enabled unless the operator sets `SMOKE_WRITES=1` after a **recorded** write
smoke on a **non-prod** agent.

- Factory smoke calls **GET tools only**. It never publishes a Page post.
- Do **not** seat write tools (`create_page_post`, comments, media publish)
  because `make factory` went green.
- SOCIAL / prod hosts keep `META_GRAPH_READ_ONLY=1` until a human approves
  live writes.

## Timebox (measured dogfood)

Measured on this repo after `pip install -e ".[dev]"` (no vendor token in CI):

| Step | What you run | This dogfood |
| --- | --- | --- |
| Discover | `make factory-list` | **0.7s** (`list-tools` → 19 Pages tools) |
| Generate | `make factory-generate` | **0.7s** (rewrites `examples/generated/meta_graph_mcp`) |
| Offline / fail-closed smoke | `make factory-smoke` | **FAIL** without `META_GRAPH_API_TOKEN` (correct); `FACTORY_LIVE=0` + token is seconds |
| Live smoke | `make factory-smoke` with a vaulted Page token | minutes once orange-prompt + vault inject work |
| Seat non-prod | mcp.json on a scratch agent | rest of the hour; not a prod SOCIAL flip |

The clock starts when the OpenAPI (or this Pages spec) is in-tree. It stops
when a **non-prod** agent has listed GET tools. Seating prod or turning on
writes is outside this ticket.

## Credentials (never commit, never chat)

Page / vendor tokens are secrets. SOCIAL must not ask for them in Slack or
chat.

1. **Orange-prompt** Jeremiah (or the operator) for a Page access token with
   `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, and
   `read_insights`. Add `pages_manage_posts` / `pages_manage_engagement` only
   when a recorded write smoke is planned.
2. Store it in the **TNT vault** (platform org). Do not write it into git,
   `tools.json`, committed `.env`, `mcp.json` in this repo, or ticket comments.
3. Inject at runtime as `META_GRAPH_API_TOKEN` (or `{PREFIX}_API_TOKEN` for
   another `--name`).

`scripts/factory_smoke.py` fails closed if that variable is unset or empty. It
prints `PASS` / `FAIL` and redacts token values, including when a vendor error
body echoes the bearer token.

## Step-by-step (Meta Graph reference)

From the repo root, after `make install`:

```bash
# 1. Discover — writes nothing
make factory-list

# 2. Generate — refreshes the committed Meta Graph server
make factory-generate

# 3. Smoke — FAIL without a token (that is correct)
make factory-smoke
```

`make factory` runs all three. Defaults are the Meta Graph files above.

With a vaulted token, live smoke calls the first GET tool (`get_current_page`
→ `GET /me`) through the generated `mcp_runtime` and does not print the Graph
body:

```bash
export META_GRAPH_API_TOKEN='…from vault…'   # never commit this line
export META_GRAPH_READ_ONLY=1                 # kill-switch; also the smoke default
make factory-smoke
```

Offline gate only (token must still be set):

```bash
FACTORY_LIVE=0 make factory-smoke
```

Another **already-known** OpenAPI (still not a factory product — same three
Make variables):

```bash
make factory \
  SPEC=examples/tickets-openapi.yaml \
  NAME=tickets \
  OUT=examples/generated/tickets_mcp \
  OVERRIDES=examples/tickets-overrides.yaml
```

`make example` is unchanged: it still defaults `SPEC` to the tickets sample.

## Seat checklist (non-prod agent only)

Do not seat prod SOCIAL, Grok Bot prod, or a customer-facing host on this
ticket.

1. Confirm `make factory-list` shows the expected GET and write tools. Writes
   stay in `tools.json`; `*_READ_ONLY=1` hides them at runtime.
2. Confirm live or offline smoke printed `PASS` and `READ_ONLY=1`.
3. Point a **scratch / non-prod** MCP host at
   `examples/generated/meta_graph_mcp/server.py` with an absolute path.
4. Inject env from the vault, never from chat:

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

5. First call: `get_current_page`. Do not request `access_token` in `fields`.
6. Leave write tools unseated. A later write smoke is a separate, recorded
   step (`SMOKE_WRITES=1` plus a human-owned non-prod POST) — not `make factory`.

## Failure modes

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `FAIL: missing META_GRAPH_API_TOKEN` | No orange-prompt / vault inject | Stop. Do not mint a token into git. Fail-closed is the correct CI/dev result. |
| `FAIL: generated server not found` | `OUT` is wrong or generate was skipped | `make factory-generate` |
| `FAIL: kill-switch` / `READ_ONLY` | Writes enabled without `SMOKE_WRITES=1` | Keep `READ_ONLY=1`. Do not seat write tools. |
| `FAIL: live … HTTP 401` | Bad, expired, or User-not-Page token | Re-prompt via orange-prompt; rotate in vault. Smoke must not print the token. |
| `FAIL: live … HTTP 4xx/5xx` | Graph permission, version, or outage | Check `pages_*` / `read_insights`; optional `META_GRAPH_BASE_URL`. |
| Smoke `PASS` but agent shows write tools | Host omitted `META_GRAPH_READ_ONLY=1` | Fix mcp.json. Kill-switch is env at **runtime**, not a generate flag. |
| Token in a PR, chat, or `tools.json` | Process break | Rotate immediately. Factory smoke fails if the token is embedded in `tools.json`. |

## Out of scope

- Ops Console UI (#331)
- Public pack / dogfood scrub (#338)
- Seating prod SOCIAL or new customer bots
- Inventing a multi-vendor factory control plane

Tip deploy: **none**. Docs and tooling only unless someone adds runtime to the
generator itself (this ticket does not).
