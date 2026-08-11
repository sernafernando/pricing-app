import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mapEntityToInputs } from './contextDataMappers';

const dia = (overrides = {}) => ({
  fecha: '2026-08-03',
  fecha_label: '03/08',
  dia_semana: 'Lun',
  entrada: '08:57',
  salida: '18:03',
  horas_decimal: 9.1,
  horas_hhmm: '09:06',
  estado: 'presente',
  sin_fichadas: false,
  incompleto: false,
  ...overrides,
});

const empleado = (dias = [], extra = {}) => ({
  empleado_id: 12,
  legajo: '0042',
  nombre_completo: 'Pérez, Juan',
  dni: '30111222',
  cuil: '20301112223',
  puesto: 'Operario',
  area: 'Depósito',
  dias,
  total_horas_decimal: 176.5,
  total_horas_hhmm: '176:30',
  total_dias: 22,
  dias_trabajados: 20,
  fecha_desde: '2026-08-01',
  fecha_hasta: '2026-08-31',
  ...extra,
});

const mapear = (...args) => mapEntityToInputs('horarios_empleado', empleado(...args));
const tabla = (inputs) => JSON.parse(inputs.tabla_dias);

describe('horariosEmpleadoMapper — cabecera', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-05T10:00:00'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('mapea la identidad del empleado y los totales', () => {
    const inputs = mapear([dia()]);

    expect(inputs.legajo).toBe('0042');
    expect(inputs.nombre_completo).toBe('Pérez, Juan');
    expect(inputs.dni).toBe('30111222');
    expect(inputs.cuil).toBe('20301112223');
    expect(inputs.puesto).toBe('Operario');
    expect(inputs.area).toBe('Depósito');
    expect(inputs.total_horas).toBe('176:30');
    expect(inputs.total_dias).toBe('22');
  });

  it('arma el período dd/mm/aaaa - dd/mm/aaaa sin correrse un día', () => {
    const inputs = mapear([dia()]);
    expect(inputs.periodo).toBe('01/08/2026 - 31/08/2026');
  });

  it('emite la fecha de emisión de hoy', () => {
    const inputs = mapear([dia()]);
    expect(inputs.fecha_emision).toBe('05/09/2026');
  });
});

describe('horariosEmpleadoMapper — filas', () => {
  it('un día normal rinde [Día, entrada, salida, horas]', () => {
    const inputs = mapear([dia()]);
    expect(tabla(inputs)).toEqual([['Lun 03/08', '08:57', '18:03', '09:06']]);
  });

  it('un día sin fichadas pone el estado EN MAYÚSCULAS en la columna Entrada', () => {
    const inputs = mapear([
      dia({
        fecha_label: '05/08',
        dia_semana: 'Mié',
        entrada: '',
        salida: '',
        horas_hhmm: '00:00',
        estado: 'vacaciones',
        sin_fichadas: true,
      }),
    ]);

    expect(tabla(inputs)).toEqual([['Mié 05/08', 'VACACIONES', '', '']]);
  });

  it('un día incompleto conserva la entrada y deja salida y horas vacías', () => {
    const inputs = mapear([
      dia({ salida: '', horas_hhmm: '00:00', horas_decimal: 0, incompleto: true }),
    ]);

    expect(tabla(inputs)).toEqual([['Lun 03/08', '08:57', '', '']]);
  });

  it('sin la columna de horas las filas tienen 3 celdas', () => {
    const inputs = mapEntityToInputs(
      'horarios_empleado',
      empleado([dia()], { incluir_horas: false })
    );

    expect(tabla(inputs)).toEqual([['Lun 03/08', '08:57', '18:03']]);
  });
});

/**
 * Antes esto verificaba la partición en DOS tablas (`ceil(n/2)` en la primera,
 * el resto en la segunda). Esa partición era el bug: pdfme apila las tablas en
 * un único flujo vertical, así que la segunda terminaba montada sobre el
 * encabezado. Ahora va UNA sola clave con todos los días y la cobertura se
 * convierte en "nada se pierde ni se reordena por el camino".
 */
describe('horariosEmpleadoMapper — una sola tabla con todos los días', () => {
  const dias = (n) =>
    Array.from({ length: n }, (_, i) => dia({ fecha_label: `${String(i + 1).padStart(2, '0')}/08` }));

  it('emite UNA sola clave de tabla, sin `tabla_dias_1` / `tabla_dias_2`', () => {
    const inputs = mapear(dias(10));

    expect(Object.keys(inputs).filter((k) => k.startsWith('tabla_'))).toEqual(['tabla_dias']);
  });

  it('mete TODOS los días en la misma tabla, sin partirlos', () => {
    expect(tabla(mapear(dias(10)))).toHaveLength(10);
    expect(tabla(mapear(dias(7)))).toHaveLength(7);
    // Un mes largo entra igual: el tope de 32 días ya no existe, pdfme pagina.
    expect(tabla(mapear(dias(45)))).toHaveLength(45);
  });

  it('conserva el orden cronológico', () => {
    const inputs = mapear(dias(5));

    expect(tabla(inputs).map((f) => f[0])).toEqual([
      'Lun 01/08',
      'Lun 02/08',
      'Lun 03/08',
      'Lun 04/08',
      'Lun 05/08',
    ]);
  });

  it('con un solo día la tabla tiene una fila', () => {
    expect(tabla(mapear(dias(1)))).toHaveLength(1);
  });

  it('sin días la tabla queda vacía (y sigue siendo JSON válido)', () => {
    expect(mapear([]).tabla_dias).toBe('[]');
  });

  it('tolera un empleado sin la clave `dias`', () => {
    const inputs = mapEntityToInputs('horarios_empleado', { legajo: '1' });
    expect(inputs.tabla_dias).toBe('[]');
  });
});
