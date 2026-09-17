# Public pack vs operator notes

This repository is a **generator** plus committed examples. Contest and import
readers should be able to clone it, generate a server from any OpenAPI 3
document, and inject a token from their own environment. They must never be
told that a particular issue tracker, vault, or seating lane is required.

| Surface | What it is | How it is configured |
|---------|------------|----------------------|
| **Public pack** | README, architecture overview, fictional tickets sample, curated Meta Graph and X Posts examples, generated servers | Zero credentials. Tokens are env-only. |
| **Operator notes** | Factory dogfood runbook, optional vault/orange-prompt habit, internal ticket pins | Optional. Not the default path. |

Companion UI: [`crew-chief-ops-console`](https://github.com/TechHandPro/crew-chief-ops-console)
(read-only console). Its #338 deny-list is the same idea: private hostnames and
secrets are env-only, never required defaults.

## Deny-list (written check)

The public pack — `README.md`, `ARCHITECTURE.md`, Makefile help text, and
committed examples under `examples/` (except optional operator notes) — must
contain **none** of the following as required values or default narrative:

1. **TechHand process IDs** — ticket numbers (`TNT #330`, `#324`, …) and
   internal lane names (SOCIAL) in the front of the README.
2. **Required vault / orange-prompt path.** Credentials come from the
   environment or a host secret manager. A vault plus out-of-band prompt may
   appear only as optional operator notes.
3. **Private operator hostnames** as required defaults. Graph defaults to
   the public `https://graph.facebook.com` API. The tickets sample uses
   `tickets.example.com`.
4. **Secret material.** No Page tokens, PEM blocks, or live API keys in git.

Allowed: Meta Graph and X Posts as *vendor examples among others*; the words
**Cursor** / **Grok Bot** as MCP hosts; the public GitHub org `TechHandPro`
in clone URLs; operator runbooks under `docs/FACTORY_LOOP.md` and
`docs/agents/` that name a crew process.

`examples/meta-graph-pages.md` and `examples/x-api.md` may include an
**Optional operator notes** section. That section is not the default path.

This document is the maintainer note that *may* name process IDs so the
split is explicit. The automated check does **not** scan this file,
[`FACTORY_LOOP.md`](FACTORY_LOOP.md), `docs/TNT_TICKET.md`, or `docs/agents/`.

## Automated proof

`tests/test_public_pack_denylist.py` (run by `pytest`) fails CI if README
prose regresses into a required TNT/SOCIAL path, or if public examples gain
private hostnames or secret markers.

```bash
python -m pytest tests/test_public_pack_denylist.py
```

## Out of scope here

- Changing factory smoke behavior
- Regenerating committed example servers
- Ops Console UI / audit surface
- Contest/template publish
