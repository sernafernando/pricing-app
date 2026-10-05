# Exploration: Controlados OC read-only exhibit

## Problem

Depósito → Controlados uses `AccordionBodyConOc`, which filters `saldo_pendiente !== 0`. After a clean control, every line is 0, so the OC table is empty. Operators still need to see what the OC contained.

## Root cause

`a7a084cd` (PR3 Depósito) added the zero-saldo hide for the control/faltantes workflow. Same panel is reused for `estado === 'controlado'`.

## Locked intent

- Controlados: show all ERP lines, exhibit only (no tanda, no control buttons).
- Recibidos / Con faltantes: keep hiding saldo 0.
- No backend / estado / tab transition changes.

## Touch

`TabRecepcionDeposito.jsx` + tests. Optional guia note.
