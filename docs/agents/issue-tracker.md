# Issue tracker contract

The issue tracker for this repository is **TNT (TechHand Network Toolkit)**. Not
GitHub Issues, not Linear, not Jira, not scratch files.

## Session start

1. `tnt_resolve_repo` to map this repository to its TNT organization and work
   ticket.
2. Read `docs/TNT_TICKET.md` if present for the pinned ticket.
3. `tnt_resolve_work_ticket(allow_create=false)`.
4. Pass `git_repository_id` on every organization-scoped MCP write.

Never post platform work to a client ticket, or client work to a platform ticket.

## Current state

This repository is **not yet linked** to a TNT organization: `tnt_resolve_repo`
returns `action_required: link_repo`, and there is no `docs/TNT_TICKET.md` pin.
Link it in TNT (Organization → Repositories) and add the pin file before using
ticket, document, or training tools against this repo. Until then, work here is
driven by the task description alone and no tickets are created.
