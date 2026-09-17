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

- Organization: TechHand Pro Solutions (`organization_id` 1, platform)
- Repository: `TechHandPro/crew-chief-middleware` (`git_repository_id` 11)
- Pinned work ticket: TNT **#324** (SOCIAL bot — Facebook + X via MCP)

See `docs/TNT_TICKET.md`. Do not resolve #324 when a middleware slice ships;
it is the long-lived SOCIAL pin. Pass `git_repository_id` 11 on every
organization-scoped TNT write.
