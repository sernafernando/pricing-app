---
name: silent-failure-hunter
description: >
  Review code for silent failures: swallowed errors, bad fallbacks, missing error propagation.
  Trigger: When reviewing error handling, fail-closed logic, broad `except Exception`, or `.catch()` fallbacks.
license: MIT
metadata:
  author: pricing-app
  version: "1.0.0"
  scope: [root, backend, frontend]
  auto_invoke:
    - "Reviewing error handling or fail-closed logic"
allowed-tools: Read, Grep, Glob, Bash
---

# Silent Failure Hunter

> Adapted from ECC `agents/silent-failure-hunter.md` (MIT, Copyright (c) 2026 Affaan Mustafa),
> source commit `b38be6a7f6350964d59328b52f0624e1d1d552d1`.

Zero tolerance for silent failures. Read-only review: report findings, do not fix them unless asked.
Run it as a subagent that loads this file, pointed at one module.

## Hunt Targets

### 1. Empty or swallowing handlers

- Python: `except Exception: pass`, `except ...: return None`, `continue` with no log.
- JS: `catch {}`, `.catch(() => [])`, `.catch(() => null)`.
- Errors turned into `None` / `[]` / `{}` with no context, so the caller cannot tell "empty" from "failed".

### 2. Inadequate logging

- Log lines without the identifiers needed to find the case (item, order, user id).
- Wrong severity: a failed write logged at `info`/`debug`.
- Log-and-forget: logged, then the function returns success.

### 3. Dangerous fallbacks

- Defaults that hide a real failure (a price of `0`, an empty promotions list, "no stock").
- Graceful-looking paths that make the downstream bug harder to diagnose.
- Modules documented as fail-closed (e.g. `backend/app/services/ml_promotions_write_service.py`,
  "fail closed against the LIVE entry"): check that every failed read before a write blocks the
  write instead of falling back to a default and writing anyway.

### 4. Error propagation

- Lost stack traces: `raise NewError(str(e))` without `from e`, or `logger.error(e)` without `exc_info`.
- Generic rethrows (`HTTPException(500)`) that drop the cause.
- Missing `await`, unhandled promise rejections, fire-and-forget tasks.

### 5. Missing error handling

- No timeout or error handling around network, file, or DB paths (HTTP calls to ML/ERP).
- No rollback around transactional work: a `db.commit()` path where an earlier exception leaves the
  session dirty, or a partial write committed after a failure.

## Output Format

For each finding:

- location (`path:line`)
- severity (critical / high / medium / low)
- issue
- impact (what the user or the data ends up with)
- fix recommendation

## Commands

```bash
# Broad handlers to start from
rg -n "except Exception|except:|\.catch\(" <path>
```
