export function formatPrice(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('es-AR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}
