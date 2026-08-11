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
const tabla1 = (inputs) => JSON.parse(inputs.tabla_dias_1);
const tabla2 = (inputs) => JSON.parse(inputs.tabla_dias_2);

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
    expect(tabla1(inputs)).toEqual([['Lun 03/08', '08:57', '18:03', '09:06']]);
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

    expect(tabla1(inputs)).toEqual([['Mié 05/08', 'VACACIONES', '', '']]);
  });

  it('un día incompleto conserva la entrada y deja salida y horas vacías', () => {
    const inputs = mapear([
      dia({ salida: '', horas_hhmm: '00:00', horas_decimal: 0, incompleto: true }),
    ]);

    expect(tabla1(inputs)).toEqual([['Lun 03/08', '08:57', '', '']]);
  });

  it('sin la columna de horas las filas tienen 3 celdas', () => {
    const inputs = mapEntityToInputs(
      'horarios_empleado',
      empleado([dia()], { incluir_horas: false })
    );

    expect(tabla1(inputs)).toEqual([['Lun 03/08', '08:57', '18:03']]);
  });
});

describe('horariosEmpleadoMapper — partición en dos tablas', () => {
  const dias = (n) =>
    Array.from({ length: n }, (_, i) => dia({ fecha_label: `${String(i + 1).padStart(2, '0')}/08` }));

  it('con cantidad PAR reparte mitad y mitad', () => {
    const inputs = mapear(dias(10));
    expect(tabla1(inputs)).toHaveLength(5);
    expect(tabla2(inputs)).toHaveLength(5);
  });

  it('con cantidad IMPAR la primera tabla se lleva ceil(n/2)', () => {
    const inputs = mapear(dias(7));
    expect(tabla1(inputs)).toHaveLength(4);
    expect(tabla2(inputs)).toHaveLength(3);
  });

  it('conserva el orden cronológico al partir', () => {
    const inputs = mapear(dias(5));
    expect(tabla1(inputs).map((f) => f[0])).toEqual([
      'Lun 01/08',
      'Lun 02/08',
      'Lun 03/08',
    ]);
    expect(tabla2(inputs).map((f) => f[0])).toEqual(['Lun 04/08', 'Lun 05/08']);
  });

  it('con un solo día la segunda tabla queda vacía', () => {
    const inputs = mapear(dias(1));
    expect(tabla1(inputs)).toHaveLength(1);
    expect(tabla2(inputs)).toEqual([]);
  });

  it('sin días ambas tablas quedan vacías (y siguen siendo JSON válido)', () => {
    const inputs = mapear([]);
    expect(inputs.tabla_dias_1).toBe('[]');
    expect(inputs.tabla_dias_2).toBe('[]');
  });

  it('tolera un empleado sin la clave `dias`', () => {
    const inputs = mapEntityToInputs('horarios_empleado', { legajo: '1' });
    expect(inputs.tabla_dias_1).toBe('[]');
    expect(inputs.tabla_dias_2).toBe('[]');
  });
});
