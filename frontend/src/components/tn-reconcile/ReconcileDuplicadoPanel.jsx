import DuplicateGroupCard from './DuplicateGroupCard';
import Paginador from './Paginador';

// DUPLICADO sub-tab body: card list + paginator. Extracted verbatim from
// `TiendaNubeReconcile.jsx` (structural extraction, PR-6 pattern).
export default function ReconcileDuplicadoPanel({
  filasVisibles,
  showPaginator,
  page,
  totalPages,
  rangeStart,
  rangeEnd,
  total,
  onPrevPage,
  onNextPage,
}) {
  return (
    <div>
      {filasVisibles.length === 0 ? (
        <p>No hay grupos duplicados para revisar.</p>
      ) : (
        filasVisibles.map((row, idx) => <DuplicateGroupCard key={`${row.ean}-${idx}`} row={row} />)
      )}
      {showPaginator && (
        <Paginador
          page={page}
          totalPages={totalPages}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          total={total}
          onPrev={onPrevPage}
          onNext={onNextPage}
        />
      )}
    </div>
  );
}
