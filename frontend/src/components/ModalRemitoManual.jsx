/**
 * ModalRemitoManual — Modal para armar un remito con items, cliente y valor declarado.
 *
 * Props:
 *   isOpen - boolean
 *   onClose - function
 *   envio - object|null (etiqueta de envío para precargar datos de cliente, opcional)
 */
import { useState, useEffect, useCallback } from 'react';
import { Search, Plus, Trash2, FileDown, Loader2, X, User, Package } from 'lucide-react';
import { useDocumentGenerator } from '../hooks/useDocumentGenerator';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import ModalTesla from './ModalTesla';
import styles from './ModalRemitoManual.module.css';

const todayStr = () => new Date().toISOString().split('T')[0];

const formatMoney = (val) => {
  if (!val && val !== 0) return '';
  return Number(val).toLocaleString('es-AR', { minimumFractionDigits: 2 });
};

export default function ModalRemitoManual({ isOpen, onClose, envio = null }) {
  const { templates, loading: loadingTemplates, generating, error: genError, fetchTemplates, generatePdf } = useDocumentGenerator('remito_manual');

  // === Cliente ===
  const [clienteNombre, setClienteNombre] = useState('');
  const [clienteCuit, setClienteCuit] = useState('');
  const [clienteDireccion, setClienteDireccion] = useState('');
  const [clienteCiudad, setClienteCiudad] = useState('');
  const [clienteCp, setClienteCp] = useState('');
  const [clienteTelefono, setClienteTelefono] = useState('');

  // === Remito ===
  const [fechaRemito, setFechaRemito] = useState(todayStr());
  const [shippingId, setShippingId] = useState('');
  const [bultos, setBultos] = useState('1');
  const [valorDeclarado, setValorDeclarado] = useState('');
  const [valorManual, setValorManual] = useState(false);
  const [observaciones, setObservaciones] = useState('');

  // === Items ===
  const [items, setItems] = useState([]);
  const [busqueda, setBusqueda] = useState('');
  const debouncedBusqueda = useDebounce(busqueda, 400);
  const [resultados, setResultados] = useState([]);
  const [buscando, setBuscando] = useState(false);

  // === Item manual ===
  const [showManualItem, setShowManualItem] = useState(false);
  const [manualCodigo, setManualCodigo] = useState('');
  const [manualDescripcion, setManualDescripcion] = useState('');
  const [manualPrecio, setManualPrecio] = useState('');

  // Precargar datos del envío si viene uno
  useEffect(() => {
    if (isOpen && envio) {
      setClienteNombre(envio.mlreceiver_name || envio.manual_receiver_name || '');
      setClienteDireccion(
        envio.direccion_completa ||
        [envio.mlstreet_name || envio.manual_street_name, envio.mlstreet_number || envio.manual_street_number].filter(Boolean).join(' ') ||
        ''
      );
      setClienteCiudad(envio.mlcity_name || envio.manual_city_name || '');
      setClienteCp(envio.mlzip_code || envio.manual_zip_code || '');
      setClienteTelefono(envio.mlreceiver_phone || envio.manual_phone || '');
      setShippingId(envio.shipping_id || '');
    }
  }, [isOpen, envio]);

  // Resetear al cerrar
  useEffect(() => {
    if (!isOpen) {
      setClienteNombre('');
      setClienteCuit('');
      setClienteDireccion('');
      setClienteCiudad('');
      setClienteCp('');
      setClienteTelefono('');
      setFechaRemito(todayStr());
      setShippingId('');
      setBultos('1');
      setValorDeclarado('');
      setValorManual(false);
      setObservaciones('');
      setItems([]);
      setBusqueda('');
      setResultados([]);
      setShowManualItem(false);
    }
  }, [isOpen]);

  // Fetch templates al abrir
  useEffect(() => {
    if (isOpen) fetchTemplates();
  }, [isOpen, fetchTemplates]);

  // Buscar productos
  useEffect(() => {
    if (debouncedBusqueda.length < 2) {
      setResultados([]);
      return;
    }
    const buscar = async () => {
      setBuscando(true);
      try {
        const { data } = await api.get('/api/buscar-productos-erp', { params: { q: debouncedBusqueda } });
        setResultados(data);
      } catch {
        setResultados([]);
      } finally {
        setBuscando(false);
      }
    };
    buscar();
  }, [debouncedBusqueda]);

  // Calcular valor declarado automático
  useEffect(() => {
    if (!valorManual) {
      const total = items.reduce((sum, item) => sum + (Number(item.cantidad) || 0) * (Number(item.precio_unitario) || 0), 0);
      setValorDeclarado(total > 0 ? String(total) : '');
    }
  }, [items, valorManual]);

  const agregarProducto = useCallback((producto) => {
    setItems((prev) => [
      ...prev,
      {
        id: `erp-${producto.item_id}`,
        codigo: producto.codigo || String(producto.item_id),
        descripcion: producto.descripcion || '',
        cantidad: '1',
        precio_unitario: producto.costo_unitario ? String(producto.costo_unitario) : '0',
      },
    ]);
    setBusqueda('');
    setResultados([]);
  }, []);

  const agregarItemManual = useCallback(() => {
    if (!manualDescripcion.trim()) return;
    setItems((prev) => [
      ...prev,
      {
        id: `manual-${Date.now()}`,
        codigo: manualCodigo.trim() || 'MANUAL',
        descripcion: manualDescripcion.trim(),
        cantidad: '1',
        precio_unitario: manualPrecio || '0',
      },
    ]);
    setManualCodigo('');
    setManualDescripcion('');
    setManualPrecio('');
    setShowManualItem(false);
  }, [manualCodigo, manualDescripcion, manualPrecio]);

  const eliminarItem = useCallback((id) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const actualizarItem = useCallback((id, field, value) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, [field]: value } : item))
    );
  }, []);

  const handleGenerate = (templateId) => {
    generatePdf(templateId, {
      cliente_nombre: clienteNombre,
      cliente_cuit: clienteCuit,
      cliente_direccion: clienteDireccion,
      cliente_ciudad: clienteCiudad,
      cliente_cp: clienteCp,
      cliente_telefono: clienteTelefono,
      fecha_remito: fechaRemito,
      shipping_id: shippingId,
      bultos,
      valor_declarado: valorDeclarado,
      observaciones,
      items,
    });
  };

  const totalCalculado = items.reduce(
    (sum, item) => sum + (Number(item.cantidad) || 0) * (Number(item.precio_unitario) || 0), 0
  );

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Remito manual"
      subtitle={shippingId ? `Envío: ${shippingId}` : undefined}
      size="lg"
    >
      <div className={styles.container}>
        {genError && <div className={styles.error}>{genError}</div>}

        {/* === CLIENTE === */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}><User size={14} /> Cliente</h3>
          <div className={styles.formGrid}>
            <div className={styles.fieldFull}>
              <label className={styles.label}>Nombre / Razón social</label>
              <input className={styles.input} value={clienteNombre} onChange={(e) => setClienteNombre(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>CUIT</label>
              <input className={styles.input} value={clienteCuit} onChange={(e) => setClienteCuit(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Teléfono</label>
              <input className={styles.input} value={clienteTelefono} onChange={(e) => setClienteTelefono(e.target.value)} />
            </div>
            <div className={styles.fieldFull}>
              <label className={styles.label}>Dirección</label>
              <input className={styles.input} value={clienteDireccion} onChange={(e) => setClienteDireccion(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Ciudad</label>
              <input className={styles.input} value={clienteCiudad} onChange={(e) => setClienteCiudad(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>CP</label>
              <input className={styles.input} value={clienteCp} onChange={(e) => setClienteCp(e.target.value)} />
            </div>
          </div>
        </div>

        {/* === ITEMS === */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.sectionTitle}><Package size={14} /> Items</h3>
            <button
              type="button"
              className="btn-tesla outline-subtle-primary sm"
              onClick={() => setShowManualItem(!showManualItem)}
            >
              <Plus size={14} /> Manual
            </button>
          </div>

          {/* Buscador de productos */}
          <div className={styles.searchBox}>
            <Search size={14} className={styles.searchIcon} />
            <input
              className={styles.searchInput}
              placeholder="Buscar producto por código o descripción..."
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
            />
            {buscando && <Loader2 size={14} className={styles.spin} />}
          </div>

          {/* Resultados de búsqueda */}
          {resultados.length > 0 && (
            <ul className={styles.searchResults}>
              {resultados.map((p) => (
                <li key={p.item_id}>
                  <button type="button" className={styles.searchResultItem} onClick={() => agregarProducto(p)}>
                    <span className={styles.resultCodigo}>{p.codigo}</span>
                    <span className={styles.resultDesc}>{p.descripcion}</span>
                    <span className={styles.resultPrecio}>
                      {p.costo_unitario ? `$${formatMoney(p.costo_unitario)}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Agregar item manual */}
          {showManualItem && (
            <div className={styles.manualItemRow}>
              <input className={styles.inputSm} placeholder="Código" value={manualCodigo} onChange={(e) => setManualCodigo(e.target.value)} />
              <input className={`${styles.inputSm} ${styles.inputFlex}`} placeholder="Descripción *" value={manualDescripcion} onChange={(e) => setManualDescripcion(e.target.value)} />
              <input className={styles.inputSm} placeholder="Precio" type="number" step="0.01" value={manualPrecio} onChange={(e) => setManualPrecio(e.target.value)} />
              <button type="button" className="btn-tesla outline-subtle-success sm" onClick={agregarItemManual} disabled={!manualDescripcion.trim()}>
                <Plus size={14} />
              </button>
            </div>
          )}

          {/* Tabla de items */}
          {items.length > 0 && (
            <table className={styles.itemsTable}>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Descripción</th>
                  <th>Cant.</th>
                  <th>P. Unit.</th>
                  <th>Subtotal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className={styles.cellCodigo}>{item.codigo}</td>
                    <td>{item.descripcion}</td>
                    <td>
                      <input
                        type="number"
                        min="1"
                        className={styles.inputMini}
                        value={item.cantidad}
                        onChange={(e) => actualizarItem(item.id, 'cantidad', e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        step="0.01"
                        className={styles.inputMini}
                        value={item.precio_unitario}
                        onChange={(e) => actualizarItem(item.id, 'precio_unitario', e.target.value)}
                      />
                    </td>
                    <td className={styles.cellSubtotal}>
                      ${formatMoney((Number(item.cantidad) || 0) * (Number(item.precio_unitario) || 0))}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.btnRemove}
                        onClick={() => eliminarItem(item.id)}
                        aria-label={`Eliminar ${item.descripcion}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {items.length === 0 && !showManualItem && (
            <p className={styles.emptyItems}>Buscá un producto o agregá uno manual</p>
          )}
        </div>

        {/* === TOTALES === */}
        <div className={styles.section}>
          <div className={styles.totalesRow}>
            <div className={styles.field}>
              <label className={styles.label}>Fecha</label>
              <input type="date" className={styles.input} value={fechaRemito} onChange={(e) => setFechaRemito(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Bultos</label>
              <input type="number" min="1" className={styles.input} value={bultos} onChange={(e) => setBultos(e.target.value)} />
            </div>
            <div className={styles.field}>
              <label className={styles.label}>
                Valor declarado
                {!valorManual && items.length > 0 && (
                  <span className={styles.autoLabel}>(auto: ${formatMoney(totalCalculado)})</span>
                )}
              </label>
              <input
                type="number"
                step="0.01"
                className={styles.input}
                value={valorDeclarado}
                onChange={(e) => { setValorManual(true); setValorDeclarado(e.target.value); }}
                onBlur={() => { if (!valorDeclarado) setValorManual(false); }}
              />
            </div>
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Observaciones</label>
            <textarea className={styles.textarea} rows={2} value={observaciones} onChange={(e) => setObservaciones(e.target.value)} />
          </div>
        </div>

        {/* === GENERAR === */}
        <div className={styles.generateSection}>
          {loadingTemplates ? (
            <span className={styles.loadingText}><Loader2 size={14} className={styles.spin} /> Cargando templates...</span>
          ) : templates.length === 0 ? (
            <span className={styles.emptyText}>No hay templates para remito_manual</span>
          ) : (
            templates.map((t) => (
              <button
                key={t.id}
                className="btn-tesla outline-subtle-primary sm"
                onClick={() => handleGenerate(t.id)}
                disabled={generating || items.length === 0}
              >
                <FileDown size={14} />
                {generating ? 'Generando...' : t.nombre}
              </button>
            ))
          )}
          <button type="button" className="btn-tesla secondary sm" onClick={onClose}>
            <X size={14} /> Cerrar
          </button>
        </div>
      </div>
    </ModalTesla>
  );
}
