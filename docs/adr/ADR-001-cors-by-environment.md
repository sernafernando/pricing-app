# ADR-001 - CORS Strategy by Environment

Status: Accepted
Date: 2026-02-10

## Context

The API currently serves both local development and production clients. Wildcard CORS may simplify local setup but is unsafe in production.

## Decision

- Development may use permissive CORS for local productivity.
- Production must use explicit allowlist origins from environment configuration.
- Any CORS change must include regression verification for authenticated browser flows.

## Consequences

- Better security posture in production.
- Slightly more configuration management across environments.

## Follow-up

- Add config variable for allowed origins.
- Add CI/static check to prevent wildcard CORS in production path.
