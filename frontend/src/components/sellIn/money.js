const MONEY = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ARS with its sign in front of the symbol, as the sell-in screens show it: "-$ 2.000,00" for a surcharge. */
export const money = (value) => {
  const n = Number(value);
  return `${n < 0 ? '-' : ''}$ ${MONEY.format(Math.abs(n))}`;
};
