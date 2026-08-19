import { useState, useEffect, useCallback } from 'react';
import { Check, X as XIcon } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { ticketsAPI, propuestasAPI } from '../services/api';
import ProvenanceBadge from './ProvenanceBadge';
import SelectorValorPropuesta, { CAMPOS_CORREGIBLES } from './SelectorValorPropuesta';
import styles from './TicketProposals.module.css';

const CAMPO_LABEL = {
  severidad: 'Severidad',
  urgencia: 'Urgencia',
  titulo: 'Título',
  resumen: 'Resumen',
  sector: 'Sector',
  tipo_ticket: 'Tipo de ticket',
  metadata_ia: 'Metadata',
};

// Fields `descartar()` can revert to a clean "unset" state once already
// applied by auto-apply — MUST mirror `CAMPOS_REVERTIBLES` in
// `backend/app/tickets/services/confirmacion_service.py` exactly. The
// backend is the enforced source of truth (409 `PropuestaNoDescartableError`
// if bypassed, e.g. a stale tab); this copy only decides whether the
// Discard button is offered at all, so a human is never shown a button
// guaranteed to fail. `titulo` is NOT NULL (no unset state), `sector`/
// `tipo_ticket` have no origen column and moving them is a domain
// operation with no defined "undo", and `metadata_ia` was a JSONB MERGE —
// there is no record of which keys it added. Adding a new revertible field
// on the backend MUST update this set too, or the two drift out of sync.
//
// NOT gating whether Confirm (ratify) renders — every already-applied
// field gets that one, revertible or not (see `handleConfirmar`'s use in
// the "aplicadas" section below).
// ponytail: ask the backend for a `descartable: bool` per proposal
// instead of duplicating this vocabulary here.
const CAMPOS_REVERTIBLES = new Set(['severidad', 'urgencia', 'resumen']);

// `confirmado_por_id == null` (loose: catches both `null` and `undefined`)
// on a `confirmada` row means the AI applied it and nobody has looked at
// it yet — see `confirmacion_service`'s module docstring. Distinct from a
// `pendiente` row, which never touched the ticket at all.
const esAplicadoSinRevisar = (p) => p.estado === 'confirmada' && p.confirmado_por_id == null;

/**
 * AI-triage proposals for one ticket that a human can still act on
 * (tickets-ai-triage PR 4c, topology flipped by
 * feat/tickets-triage-aplicar-directo). Two shapes, never mixed in the same
 * list item:
 *
 * - `pendiente`: the original "AI proposes, human confirms" flow — nothing
 *   was written to the ticket yet. Survives when `TICKETS_TRIAGE_AUTO_APPLY`
 *   is off, or a field was gated by confidence. Confirm/discard here read
 *   as "approve this proposal", same as before.
 * - `confirmada` + `confirmado_por_id IS NULL` (`ia_auto`): the AI ALREADY
 *   applied this value — the ticket shows it right now. "Confirm" here
 *   RATIFIES it (marks it reviewed, never rewrites the ticket — the value
 *   is already there); "Discard" CORRECTS it, only offered for
 *   `CAMPOS_REVERTIBLES` (real pre-push review finding: without ratify, a
 *   non-revertible field like titulo/sector/tipo_ticket/metadata_ia had NO
 *   way to ever leave "unreviewed" — the exact eternal-pending-count
 *   problem this feature was built to eliminate, for a different subset
 *   of fields).
 *
 * Confidence is always visible, independent of permission — only the
 * confirm/discard/batch controls require `tickets.triage.confirmar`. Batch
 * confirm always sends exactly ONE request with every selected id, and only
 * ever includes `pendiente` proposals (nothing to batch-confirm on values
 * already applied).
 */
export default function TicketProposals({ ticketId, onChanged, refreshToken }) {
  const { tienePermiso } = usePermisos();
  const puedeConfirmar = tienePermiso('tickets.triage.confirmar');

  const [propuestas, setPropuestas] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busyId, setBusyId] = useState(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [error, setError] = useState(null);
  // propuesta.id -> value the user picked in SelectorValorPropuesta, only
  // present once they've touched the selector (PR2). Absent means "still
  // the AI's own value" — see `valorCorregidoPara` below.
  const [seleccion, setSeleccion] = useState({});

  const fetchPropuestas = useCallback(async () => {
    try {
      const { data } = await ticketsAPI.listarPropuestas(ticketId);
      setPropuestas(Array.isArray(data) ? data : []);
    } catch {
      setPropuestas([]);
    }
  }, [ticketId]);

  useEffect(() => {
    fetchPropuestas();
    // refreshToken is an external re-fetch trigger (fix/tickets-triage-
    // backfill) — bumping it forces this effect to rerun even when
    // ticketId/fetchPropuestas are unchanged.
  }, [fetchPropuestas, refreshToken]);

  const toggleSelected = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Undefined unless the user actually picked a different value than the
  // AI proposed — never sent as an explicit `undefined` argument (see
  // `handleConfirmar`), so an untouched selector keeps confirm a one-click
  // ratification with today's exact request shape.
  const valorCorregidoPara = (p) => {
    const elegido = seleccion[p.id];
    const original = p.valor_propuesto?.valor;
    return elegido && elegido !== original ? elegido : undefined;
  };

  const handleConfirmar = async (id, valorCorregido) => {
    setBusyId(id);
    setError(null);
    try {
      // Branching (not `propuestasAPI.confirmar(id, valorCorregido)`
      // unconditionally) so an untouched selector never sends an explicit
      // `undefined` second argument — see `api.propuestas.test.js`'s
      // "no stray second argument" regression guard.
      if (valorCorregido !== undefined) {
        await propuestasAPI.confirmar(id, valorCorregido);
      } else {
        await propuestasAPI.confirmar(id);
      }
      await fetchPropuestas();
      onChanged?.();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al confirmar la propuesta');
    } finally {
      setBusyId(null);
    }
  };

  const handleDescartar = async (id) => {
    setBusyId(id);
    setError(null);
    try {
      await propuestasAPI.descartar(id);
      await fetchPropuestas();
      // Real pre-push review finding: before this feature, `descartar()`
      // never wrote to `tickets` — no need to refresh the parent's ticket
      // view. Now it can clear an already-applied ia_auto value, so the
      // ticket detail must refetch too, or it keeps showing the stale
      // value until the user manually reloads.
      onChanged?.();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al descartar la propuesta');
    } finally {
      setBusyId(null);
    }
  };

  const handleConfirmarSeleccionadas = async () => {
    setBatchBusy(true);
    setError(null);
    try {
      await propuestasAPI.confirmarBatch(Array.from(selected));
      setSelected(new Set());
      await fetchPropuestas();
      onChanged?.();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al confirmar las propuestas seleccionadas');
    } finally {
      setBatchBusy(false);
    }
  };

  const pendientes = propuestas.filter((p) => p.estado === 'pendiente');
  const aplicadas = propuestas.filter(esAplicadoSinRevisar);

  // Nothing to show: no proposals at all, or every one of them is a shape
  // this component doesn't render (e.g. a human-confirmed `ia_confirmada`
  // row, which the backend already excludes but this guard agrees
  // independently rather than rendering an empty shell).
  if (pendientes.length === 0 && aplicadas.length === 0) return null;

  return (
    <div className={styles.container}>
      {error && <div className={styles.inlineError}>{error}</div>}

      {pendientes.length > 0 && (
        <>
          <div className={styles.header}>
            <span className={styles.title}>Propuestas de IA pendientes</span>
            {puedeConfirmar && selected.size > 0 && (
              <button className={styles.btnBatch} onClick={handleConfirmarSeleccionadas} disabled={batchBusy}>
                <Check size={13} />
                {batchBusy ? 'Confirmando...' : `Confirmar seleccionadas (${selected.size})`}
              </button>
            )}
          </div>

          <ul className={styles.list}>
            {pendientes.map((p) => {
              const label = CAMPO_LABEL[p.campo] || p.campo;
              const esCorregible = CAMPOS_CORREGIBLES.has(p.campo);
              return (
                <li key={p.id} className={styles.item}>
                  {puedeConfirmar && (
                    <input
                      type="checkbox"
                      className={styles.checkbox}
                      checked={selected.has(p.id)}
                      onChange={() => toggleSelected(p.id)}
                      aria-label={`Seleccionar propuesta ${label}`}
                    />
                  )}
                  <span className={styles.label}>
                    {esCorregible ? (
                      <>
                        {label}:{' '}
                        <SelectorValorPropuesta
                          campo={p.campo}
                          valorPropuesto={p.valor_propuesto?.valor}
                          value={seleccion[p.id]}
                          onChange={(v) => setSeleccion((prev) => ({ ...prev, [p.id]: v }))}
                          disabled={busyId === p.id}
                        />
                      </>
                    ) : (
                      <>
                        {label}: {String(p.valor_propuesto?.valor ?? '-')}
                      </>
                    )}
                    {typeof p.confianza === 'number' && (
                      <span className={styles.confianza}> · IA {p.confianza.toFixed(2)}</span>
                    )}
                    {typeof p.ejemplos_usados === 'number' && (
                      <span className={styles.confianza}> · {p.ejemplos_usados} ejemplos aprendidos</span>
                    )}
                  </span>
                  {puedeConfirmar && (
                    <span className={styles.actions}>
                      <button
                        className={styles.btnConfirm}
                        onClick={() => handleConfirmar(p.id, valorCorregidoPara(p))}
                        disabled={busyId === p.id}
                        aria-label={`Confirmar ${label}`}
                      >
                        <Check size={13} />
                      </button>
                      <button
                        className={styles.btnDiscard}
                        onClick={() => handleDescartar(p.id)}
                        disabled={busyId === p.id}
                        aria-label={`Descartar ${label}`}
                      >
                        <XIcon size={13} />
                      </button>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {aplicadas.length > 0 && (
        <>
          <div className={styles.header}>
            <span className={styles.title}>Clasificado por IA — corregí si está mal</span>
          </div>

          <ul className={styles.list}>
            {aplicadas.map((p) => {
              const label = CAMPO_LABEL[p.campo] || p.campo;
              const esRevertible = CAMPOS_REVERTIBLES.has(p.campo);
              const esCorregible = CAMPOS_CORREGIBLES.has(p.campo);
              return (
                <li key={p.id} className={styles.item}>
                  <span className={styles.label}>
                    {esCorregible ? (
                      <>
                        {label}:{' '}
                        <SelectorValorPropuesta
                          campo={p.campo}
                          valorPropuesto={p.valor_propuesto?.valor}
                          value={seleccion[p.id]}
                          onChange={(v) => setSeleccion((prev) => ({ ...prev, [p.id]: v }))}
                          disabled={busyId === p.id}
                        />
                      </>
                    ) : (
                      <>
                        {label}: {String(p.valor_propuesto?.valor ?? '-')}
                      </>
                    )}
                    {typeof p.confianza === 'number' && (
                      <span className={styles.confianza}> · IA {p.confianza.toFixed(2)}</span>
                    )}
                    {typeof p.ejemplos_usados === 'number' && (
                      <span className={styles.confianza}> · {p.ejemplos_usados} ejemplos aprendidos</span>
                    )}
                    <ProvenanceBadge origen="ia_auto" />
                  </span>
                  {puedeConfirmar && (
                    <span className={styles.actions}>
                      <button
                        className={styles.btnConfirm}
                        onClick={() => handleConfirmar(p.id, valorCorregidoPara(p))}
                        disabled={busyId === p.id}
                        aria-label={`Confirmar ${label}`}
                        title="Ya se aplicó automáticamente — marcalo como revisado si está bien"
                      >
                        <Check size={13} />
                      </button>
                      {esRevertible && (
                        <button
                          className={styles.btnDiscard}
                          onClick={() => handleDescartar(p.id)}
                          disabled={busyId === p.id}
                          aria-label={`Descartar ${label}`}
                          title="Ya se aplicó automáticamente — descartalo si está mal"
                        >
                          <XIcon size={13} />
                        </button>
                      )}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
