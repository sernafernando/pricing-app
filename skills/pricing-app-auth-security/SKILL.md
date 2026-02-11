---
name: pricing-app-auth-security
description: JWT, authz, CORS, and secrets guardrails for Pricing App backend
license: MIT
metadata:
  author: pricing-app
  version: "1.0.0"
  scope: [backend, root]
  auto_invoke:
    - "Refactoring JWT/auth flows"
    - "Adding refresh tokens or token checks"
    - "Changing auth on API endpoints"
    - "Modifying CORS or security settings"
    - "Reviewing endpoint exposure risks"
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# Pricing App Auth Security

## Trigger

Use this skill when touching authentication, authorization, JWT, CORS, or endpoint exposure.

## Critical Rules

- ALWAYS protect sensitive endpoints with authentication.
- ALWAYS enforce permission checks for write operations.
- ALWAYS validate token type (access vs refresh).
- ALWAYS return `401` for invalid/expired/missing auth and `403` for insufficient permissions.
- NEVER use wildcard CORS in production paths.
- NEVER log tokens, secrets, passwords, or raw credentials.

## Required Checks by Change Type

### JWT/Auth changes

- Login issues both access and refresh tokens.
- Refresh endpoint rejects access tokens and invalid refresh tokens.
- Disabled/inactive users cannot obtain or refresh valid sessions.
- Protected endpoints still reject anonymous access.

### Endpoint security changes

- No endpoint unintentionally becomes public.
- Permission checks remain in place for all write actions.
- Error messages are safe (no secret leakage).

### CORS changes

- Production origins are explicit and environment-driven.
- Local development can remain permissive if required.

## Minimal Test Matrix (must pass)

1. Login success/failure.
2. Refresh success/failure/invalid token type.
3. Protected endpoint without token -> `401`.
4. Protected write with insufficient permission -> `403`.

## PR Output Contract

Include in PR summary:

- Which endpoints stayed protected and how verified.
- Exact tests run for login/refresh/401/403 cases.
- Any remaining risk and rollback path.

## Anti-Patterns

- Adding auth logic without regression tests.
- Broad `except Exception` hiding token validation errors.
- Coupling permission checks to UI-only controls.
- Returning different auth error formats per endpoint.

## References

- `AGENTS.md`
- `backend/app/core/security.py`
- `backend/app/api/endpoints/auth.py`
- `skills/pricing-app-permissions/SKILL.md`
