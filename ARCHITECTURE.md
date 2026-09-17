# Architecture

The goal is narrow: let an agent call a vendor's business API through MCP tools it
can discover at runtime, and keep browser automation as a last resort rather than
the integration strategy.

Four stages, each with one job.

```
   OpenAPI 3.x                     tools.json                    MCP client
   document        Discover        + mcp_runtime/     Connect     (Cursor, Grok Bot)
      │      ──────────────►            │         ──────────────►        │
      │                                 │                                │
      └── vendor docs, spec URL         └── Generate                      └── Specialize
                                            (one directory,                  (curate, compose,
                                             no vendor coupling)              only then browser)
```

## Discover

`src/openapi_to_mcp/discovery.py` turns a document into an intermediate
representation (`model.py`), deliberately separate from both OpenAPI and MCP.

- One operation becomes one tool. `operationId` gives the name (snake_cased);
  otherwise the method and path do, so specs with sloppy metadata still work.
  Collisions get numeric suffixes, and names are stable across regenerations.
- Path, query, and header parameters plus the request body become the tool's
  arguments. Each argument's schema is translated to plain JSON Schema:
  `#/components/schemas/X` references become `#/$defs/X` entries collected per
  tool, so recursive schemas survive instead of being inlined forever.
  OpenAPI-only keywords (`nullable`, `discriminator`, `xml`) are converted or
  dropped. `additionalProperties: false` keeps models from inventing arguments.
- Security schemes are mapped to credential *names*, not values: bearer, apiKey
  (header or query), and basic are supported; OAuth2 and OpenID Connect fall back
  to a pre-obtained token from the environment with a warning.
- Anything unsupported (cookie parameters, exotic content types, unresolvable
  servers) produces a warning rather than a silent omission. Unsupported
  *external* `$ref`s are a hard error with a bundling hint, because silently
  dropping a schema would mislead the agent.

Discovery never touches the network and never writes files, which is why
`list-tools` is safe to run against an unfamiliar spec.

## Generate

`src/openapi_to_mcp/generator.py` writes a directory that does not depend on this
tool at run time:

| File | Role |
| --- | --- |
| `tools.json` | the manifest: tool names, descriptions, JSON Schemas, HTTP bindings, auth env var names |
| `server.py` | entry point, plus the specialization seams |
| `mcp_runtime/` | a vendored copy of `openapi_to_mcp/runtime/`, renamed |
| `.env.example` | every environment variable the server reads |
| `README.md` | per-service quickstart and tool table |
| `mcp.example.json` | client config skeleton (`mcp.json` itself is git-ignored) |
| `Dockerfile` | container image; the placeholder for the future HTTP transport |
| `requirements.txt` | `mcp`, `httpx`, `anyio` — nothing else |

**Why a manifest plus a runtime instead of emitting Python per operation.** The
part that varies between vendors is data (paths, parameters, schemas); the part
that must be correct is logic (auth, validation, retries, redaction, MCP wiring).
Emitting the data and vendoring the logic means a spec with 400 operations
produces a 400-entry JSON file rather than 400 functions to review, the logic is
tested once here, and regeneration cannot clobber hand-written tools. The cost is
that tools are dispatched dynamically instead of being readable Python functions;
`list-tools` and `tools.json` exist so the surface is still inspectable.

**Why the runtime is vendored rather than imported.** A generated server is
something you commit to an ops repo and run for months. Copying the runtime keeps
its dependency list to the official MCP SDK plus `httpx`, so a generated server
never breaks because the generator moved on. Regenerating updates the copy.

## Connect

`src/openapi_to_mcp/runtime/` serves the manifest over MCP.

- `manifest.py` loads and validates `tools.json`, rejecting a manifest written by
  a newer generator (`manifest_version`).
- `config.py` derives all settings from `<PREFIX>_*` environment variables and
  validates the base URL.
- `auth.py` resolves credentials from the environment and knows how to redact
  them.
- `http.py` maps arguments onto a request, executes it, and shapes the response
  into text plus optional structured content.
- `server.py` wires the tool list and dispatcher onto the official MCP Python
  SDK's low-level `Server` and runs it over stdio.

**Why the low-level SDK API and not the decorator/`MCPServer` style.** Tools here
are described by data, and their schemas come from the spec. The low-level API
takes `list_tools` and `call_tool` handlers directly, so a manifest maps onto it
without generating Python signatures and without losing schema fidelity in the
round trip.

**Why stdio first.** It is what MCP clients support universally today, it needs no
listening port, and each agent session gets an isolated process with its own
credentials in its own environment. Streamable HTTP is the roadmap item for
sharing one process between many agents; that is a transport swap in
`runtime/server.py`, not a redesign.

### Trust boundaries

```
 model / agent ──arguments──►  runtime  ──HTTP──►  vendor API
      (untrusted)              (validates,        (fixed host from config)
                                fixed host,
                                redacts)
   environment ──credentials──►  runtime           (never on disk, never logged)
```

The model chooses arguments; it does not choose hosts, headers it was not given,
or credentials. Concretely, in the runtime: unknown and missing arguments are
rejected before a request is built; path values are URL-encoded; the base URL
comes only from configuration; redirects are not followed; HTTPS is required
outside loopback unless explicitly overridden; responses are size-capped; only
idempotent methods are retried; write tools can be disabled entirely with
`*_READ_ONLY`; and API errors come back as tool errors (`is_error`) so the agent
can react instead of the session failing.

## Specialize

Discovery is mechanical, and mechanical tool surfaces are rarely the ones you want
an agent to see. Three seams, in increasing order of effort:

1. **Filter** with `--include` / `--exclude` globs.
2. **Curate** with an overrides file: rename tools, rewrite descriptions for the
   model, hide operations. This is where vendor jargon becomes language an agent
   understands.
3. **Compose** in the generated `server.py`: `EXTRA_TOOLS` adds hand-written
   `LocalTool`s (one agent-shaped action from several API calls), and `CUSTOMIZE`
   narrows or reorders the generated list. Both survive regeneration, because
   regeneration rewrites `tools.json` and `mcp_runtime/`, not your entry point.

### Browser automation is the last resort

Ordered preference for reaching a vendor system:

1. A documented API with a spec — generate tools from it.
2. A documented API without a spec — hand-write a `tools.json` for the endpoints
   you need; the runtime does not care where the manifest came from.
3. No API for that capability — only then drive the UI, in a separate component,
   for the smallest possible slice.

Browser automation is slow, brittle against redesigns, and hard to audit. Every
capability that moves from step 3 to step 1 or 2 removes a class of failure. The
generator exists to make step 1 cheap enough that step 3 stops being the default.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/openapi_to_mcp/discovery.py`, `refs.py`, `naming.py`, `model.py` | Discover |
| `src/openapi_to_mcp/generator.py`, `manifest.py`, `templates/` | Generate |
| `src/openapi_to_mcp/runtime/` | Connect (also vendored into every generated server) |
| `src/openapi_to_mcp/overrides.py` | Specialize |
| `src/openapi_to_mcp/cli.py` | `generate`, `list-tools` |
| `examples/` | fictional tickets spec, curated Meta Graph Pages spec, overrides, and committed generated servers |
| `tests/` | unit tests plus a real subprocess MCP handshake |

## Known limits

- OpenAPI 3.x only; Swagger 2.0 must be converted first, and external `$ref`s must
  be bundled.
- Parameter serialization covers the common styles: repeated query parameters for
  arrays, JSON for object-valued query parameters. Exotic `style`/`explode`
  combinations are not modelled.
- One security scheme per generated server; per-operation security is not applied
  individually.
- Response schemas are not used to declare tool output schemas yet, so structured
  content is returned as-is.
- No pagination following: an agent calls the next page itself with the cursor
  the API returned.
