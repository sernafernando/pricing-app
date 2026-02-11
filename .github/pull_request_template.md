## Scope

- What changed:
- Intentionally not changed:

## Validation

List exact commands and outcomes.

```bash
# Example
pytest backend/tests/integration -q
npm run lint --prefix frontend
```

- Result:

## Risks

- Known edge cases:
- Follow-up tasks:

## Rollback

- Safest rollback path:

## Checklist

- [ ] Auth and permissions are preserved where required
- [ ] Tests added/updated for behavior changes
- [ ] No secrets included in code, logs, or config
- [ ] Migrations included for schema changes (if applicable)
- [ ] Docs updated if behavior/contracts changed
