```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:682ef0a16e529528caad81640f658baef8cbb998e15eb41ac8d1ec7fb2aa4b9e
verdict: pass
blockers: 0
critical_findings: 0
requirements: 1/1
scenarios: 3/3
test_command: cd frontend && pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx
test_exit_code: 0
test_output_hash: sha256:213041fbb06840aefb1772ff7fa034b0c02d3a03dd96352768d17e41257da376
build_command: pnpm --dir frontend exec eslint src/components/compras/TabRecepcionDeposito.jsx src/components/compras/TabRecepcionDeposito.test.jsx
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: fix-compras-deposito-controlados-oc-readonly
**Version**: uncommitted on `fix/compras-deposito-controlados-oc-readonly` @ `3b128358`
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 7 |
| Tasks complete | 7 |
| Tasks incomplete | 0 |

### Spec Compliance
| Requirement | Scenario | Result |
|-------------|----------|--------|
| Controlados CON-OC shows OC lines read-only | Controlados shows lines with saldo 0 | COMPLIANT |
| Controlados CON-OC shows OC lines read-only | Controlados has no control controls | COMPLIANT |
| Controlados CON-OC shows OC lines read-only | Recibido still hides saldo 0 lines | COMPLIANT |

### Verdict
PASS — Controlados exhibits all ERP lines read-only; recibido/faltantes keep zero-saldo hide. Vitest bundle includes TabRecepcionDeposito (64+). No full suite on this machine.
