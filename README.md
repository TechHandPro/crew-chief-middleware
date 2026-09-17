# crew-chief-middleware

Turn a vendor's OpenAPI document into a running MCP server, so agents (Grok Bot,
Cursor, anything else that speaks MCP) call business APIs directly instead of
driving a browser.

Point the generator at a spec, get a self-contained MCP server with one tool per
API operation, JSON Schema arguments an agent can actually fill in, and
credentials read from the environment. Nothing in this repo is tied to a
particular vendor, tenant, or shop: the sample API is fictional and no
credentials are ever written to disk.

```bash
openapi_to_mcp generate --spec examples/tickets-openapi.yaml --out out/tickets --name tickets
```

```
examples/tickets-openapi.yaml          out/tickets/
  7 operations              ─────►      tools.json     7 MCP tools, JSON Schema args
  bearerAuth                            server.py      stdio entry point
  https://tickets.example.com           mcp_runtime/   vendored runtime (mcp + httpx)
                                        .env.example   TICKETS_API_TOKEN, limits, safety
```

## Generate and run in under 10 minutes

Requires Python 3.11 or newer.

```bash
# 1. install the generator (2 min)
git clone <this repo> && cd crew-chief-middleware
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 2. look before you generate: which tools would this spec produce? (1 min)
openapi_to_mcp list-tools --spec examples/tickets-openapi.yaml --name tickets

# 3. generate the server (seconds)
openapi_to_mcp generate --spec examples/tickets-openapi.yaml --out out/tickets --name tickets

# 4. run it against your API (5 min: credentials and a base URL)
pip install -r out/tickets/requirements.txt
export TICKETS_API_TOKEN='...'                      # never committed, never written to disk
export TICKETS_BASE_URL='https://api.your-vendor.com/v1'   # optional if the spec has a server
export TICKETS_READ_ONLY=1                          # optional: expose only GET-style tools first
python out/tickets/server.py                        # speaks MCP on stdin/stdout, logs to stderr
```

The process looks idle because it is waiting for MCP JSON-RPC on stdin. That is
what an MCP client attaches to. Committed examples of the output live in
[`examples/generated/tickets_mcp`](examples/generated/tickets_mcp) (fictional
service desk) and [`examples/generated/meta_graph_mcp`](examples/generated/meta_graph_mcp)
(one real vendor: a curated Facebook Pages / Meta Graph subset). How to
generate that second example, including `META_GRAPH_READ_ONLY=1` and token
injection, is in [`examples/meta-graph-pages.md`](examples/meta-graph-pages.md).

Swap in a real spec by changing three things: `--spec`, `--name` (which also sets
the environment variable prefix), and the credentials you export.

## Connect it to an MCP client

Every generated project ships an `mcp.example.json` for exactly this. Use an
absolute path to `server.py`, and supply credentials the way your client
supports — inherited environment, its own `env` block, or a secret manager.

**Cursor** — `~/.cursor/mcp.json` for every project, or `.cursor/mcp.json` for one:

```json
{
  "mcpServers": {
    "tickets": {
      "command": "/absolute/path/to/out/tickets/.venv/bin/python",
      "args": ["/absolute/path/to/out/tickets/server.py"],
      "env": {
        "TICKETS_BASE_URL": "https://api.your-vendor.com/v1",
        "TICKETS_API_TOKEN": "…injected from your secret manager…"
      }
    }
  }
}
```

Restart Cursor, open the MCP settings pane, and the tools appear under the
`tickets` server. Ask for something the API covers ("list open tickets assigned
to me") and the agent calls `list_tickets` instead of opening a browser.

**Grok Bot or any other MCP host** — the same three facts: run
`python /absolute/path/to/server.py`, keep stdin/stdout attached, and pass the
`*_API_TOKEN` / `*_BASE_URL` variables in the child environment. Anything that
can launch a stdio MCP server can host these. For a container instead of a
virtualenv, each generated project also has a `Dockerfile`
(`docker run --rm -i --env-file .env tickets-mcp`).

Start with `*_READ_ONLY=1` while you are still deciding which write operations an
agent should be trusted with; the server then advertises only non-mutating tools.
Keep that flag on for any vendor that can publish or mutate until a human has
approved live writes. Tokens come from the process environment or your host's
secret manager — never from chat and never from a committed file.

## Vendor example: Meta Graph Pages

Facebook has no solid marketplace MCP plugin, so this repo includes a **small**
Pages-focused spec as a second example — not the entire Graph API, and not the
official WhatsApp-only `facebook/openapi`. It is one vendor among others; the
tickets sample is the other committed one, and any OpenAPI 3 document can take
the same path.

```bash
openapi_to_mcp generate \
  --spec examples/meta-graph-pages-openapi.yaml \
  --out examples/generated/meta_graph_mcp \
  --name meta_graph \
  --overrides examples/meta-graph-pages-overrides.yaml \
  --force
```

| Env | Purpose |
| --- | --- |
| `META_GRAPH_API_TOKEN` | Page access token (environment or secret manager) |
| `META_GRAPH_READ_ONLY=1` | Hide create/comment/media publish tools |
| `META_GRAPH_BASE_URL` | Optional Graph host/version override (spec default `https://graph.facebook.com/v24.0`) |

Never commit the token. Operator notes, a sample `mcp.json` shape, and Graph
permissions: [`examples/meta-graph-pages.md`](examples/meta-graph-pages.md).

The same discover → generate → fail-closed `READ_ONLY` smoke → seat a
**non-prod** agent loop is documented in
[`docs/FACTORY_LOOP.md`](docs/FACTORY_LOOP.md). `make factory` runs that
dogfood path against the Meta Graph files. It is not a multi-vendor factory
product.

## How it works

Four stages, described in full in [ARCHITECTURE.md](ARCHITECTURE.md):

| Stage | What happens | Where |
| --- | --- | --- |
| **Discover** | parse the OpenAPI document; one operation becomes one tool with a JSON Schema | `src/openapi_to_mcp/discovery.py` |
| **Generate** | write `tools.json` plus a vendored runtime and entry point | `src/openapi_to_mcp/generator.py` |
| **Connect** | serve those tools over MCP stdio, execute HTTP, shape responses | `src/openapi_to_mcp/runtime/` |
| **Specialize** | curate names and descriptions, hide operations, add composite tools | `overrides.py`, `server.py` seams |

The generated server is data plus a runtime, not thousands of lines of emitted
Python: `tools.json` holds names, descriptions, schemas, and HTTP bindings, and
the vendored `mcp_runtime/` package interprets it. Regenerating a service after a
vendor ships new endpoints rewrites data, never your hand-written code.

Browser automation stays available as a last resort for the parts of a vendor's
product that have no API — but it is the fallback, not the interface.

## CLI

```
openapi_to_mcp generate --spec PATH --out DIR --name NAME [options]
openapi_to_mcp list-tools --spec PATH [--name NAME] [--json]
```

| Option | Purpose |
| --- | --- |
| `--spec PATH` | OpenAPI 3.x document, JSON or YAML |
| `--out DIR` | where to write the generated server |
| `--name NAME` | service name; drives tool naming and the env var prefix |
| `--base-url URL` | override the spec's `servers[0]` |
| `--env-prefix PREFIX` | override the derived env var prefix |
| `--include GLOB` / `--exclude GLOB` | keep or drop tools by name pattern (repeatable) |
| `--overrides FILE` | rename, re-describe, or hide tools ([example](examples/tickets-overrides.yaml)) |
| `--force` | overwrite an existing generated project |
| `--quiet` | errors only |

`list-tools` writes nothing, which makes it the safe first look at an unfamiliar
spec. `--json` output is meant for scripts and agents.

## Security model

Production integrations hold real credentials for systems of record, so the
defaults are deliberately strict:

- **Credentials come from the environment only.** They are never written into
  `tools.json`, never logged, and are redacted from any error text handed back to
  a model. `.env` and `mcp.json` are git-ignored in generated projects.
- **The host is fixed by configuration, not by tool arguments.** A model chooses
  arguments; it cannot point a credentialed request at another origin.
- **HTTPS unless you say otherwise.** Plaintext HTTP to anything but loopback
  needs `*_ALLOW_INSECURE_HTTP=1`. Base URLs with embedded credentials are
  refused.
- **Redirects are not followed**, so credentials cannot be replayed to a
  redirect target.
- **Read-only mode** (`*_READ_ONLY=1`) advertises and permits only GET, HEAD, and
  OPTIONS tools.
- **Responses are capped** (`*_MAX_RESPONSE_BYTES`, default 100 kB) so one large
  payload cannot flood an agent's context, and only idempotent requests are
  retried.
- **Argument validation happens locally**: unknown or missing arguments are
  rejected before a request leaves the process.

## Specialize

A raw spec often exposes more surface than an agent should see. Three seams, in
increasing order of effort:

1. `--include` / `--exclude` globs for quick curation.
2. An overrides file to rename tools, rewrite descriptions for the model, or hide
   operations — see [`examples/tickets-overrides.yaml`](examples/tickets-overrides.yaml).
3. `EXTRA_TOOLS` and `CUSTOMIZE` in the generated `server.py`, for hand-written
   tools that compose several API calls into one agent-shaped action.

## Develop

```bash
make install     # editable install with dev extras
make test        # pytest, including a real subprocess MCP handshake
make lint        # ruff
make example     # regenerate tickets_mcp and meta_graph_mcp
make factory     # Meta Graph dogfood: list-tools → generate → smoke
```

The test suite covers OpenAPI to tool-list translation, argument mapping, the
safety rails, and an end-to-end run where a generated server is launched as a
subprocess and driven over stdio against a throwaway HTTP API. Tests also fail
if a committed example (`tickets_mcp` or `meta_graph_mcp`) drifts from what the
generator produces.

## Roadmap

- **Streamable HTTP transport** so one long-lived container can serve many
  agents; the generated `Dockerfile` is the placeholder for it today.
- **Spec discovery** from a URL, plus vendor spec registries and pinning to a
  fetched spec's digest.
- **OAuth2 client-credentials flow** in the runtime (today a pre-obtained token is
  read from the environment).
- **Response projections** so a tool can return the three fields an agent needs
  instead of an entire record.
- **Pagination helpers**, cursor following, and rate-limit awareness per vendor.
- **Recipes** for spec-less vendors: hand-written manifests, then browser
  automation only where an API genuinely does not exist.

## Non-goals for this MVP

No hosted control plane, no credential storage, and no browser automation in
this repo. The fictional tickets sample and the curated Meta Graph Pages subset
are regeneratable examples, not production connectors: they never include
tokens. A particular issue tracker, vault, or seating ritual is never required
to generate or run a server. ConnectWise-class PSA connectors are still out of
scope.
