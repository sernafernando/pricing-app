export const isBlank = (value) => value === null || value === undefined;

/** A rate as es-AR text with up to 2 decimals: 3,8 / 21 / 4,17. */
export const formatRate = (value) => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 }).format(Number(value));
