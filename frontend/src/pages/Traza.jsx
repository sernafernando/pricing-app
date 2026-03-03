/**
 * Traza -- Pagina standalone de consulta de traza unificada.
 *
 * Permite buscar por:
 * - Numero de serie
 * - ML ID (venta MercadoLibre)
 * - Numero de factura (tipo + punto de venta + numero)
 * - # de cliente (cust_id)
 * - DNI/CUIT del cliente
 * - Usuario de MercadoLibre (nickname)
 *
 * Muestra la historia completa: movimientos, facturas, pedidos, RMAs.
 * Accesible con permiso traza.ver.
 */

import { useState } from 'react';
import { Search, ScanBarcode, ShoppingCart, FileText, UserSearch, CreditCard, AtSign } from 'lucide-react';
import api from '../services/api';
import TrazaViewer from '../components/TrazaViewer';
import TrazaClienteViewer from '../components/TrazaClienteViewer';
import styles from './Traza.module.css';

const MODOS = [
  { id: 'serial', label: 'Serial', icon: ScanBarcode, placeholder: 'Numero de serie...', group: 'producto' },
  { id: 'ml', label: 'ML ID', icon: ShoppingCart, placeholder: 'ID de venta MercadoLibre (ej: 2000...)', group: 'producto' },
  { id: 'factura', label: 'Factura', icon: FileText, placeholder: null, group: 'producto' },
  { id: 'cliente', label: '# Cliente', icon: UserSearch, placeholder: 'Numero de cliente...', group: 'cliente' },
  { id: 'dni', label: 'DNI/CUIT', icon: CreditCard, placeholder: 'DNI o CUIT (ej: 20123456789)', group: 'cliente' },
  { id: 'ml_user', label: 'Usuario ML', icon: AtSign, placeholder: 'Nickname de MercadoLibre...', group: 'cliente' },
];

const MODOS_CLIENTE = new Set(['cliente', 'dni', 'ml_user']);

export default function Traza() {
  const [modo, setModo] = useState('serial');
  const [query, setQuery] = useState('');
  // Factura mode: separate fields
  const [facTipo, setFacTipo] = useState('A');
  const [facPV, setFacPV] = useState('');
  const [facNro, setFacNro] = useState('');

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Pagination for client results
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const buscar = async (overridePage = null) => {
    const currentPage = overridePage ?? page;
    setLoading(true);
    setError(null);
    if (overridePage === null) setResult(null);

    try {
      let data;
      if (modo === 'serial') {
        if (!query.trim()) return;
        const res = await api.get(`/seriales/traza/${encodeURIComponent(query.trim())}`);
        data = res.data;
      } else if (modo === 'ml') {
        if (!query.trim()) return;
        const res = await api.get(`/seriales/traza/ml/${encodeURIComponent(query.trim())}`);
        data = res.data;
      } else if (modo === 'factura') {
        if (!facPV.trim() || !facNro.trim()) return;
        const res = await api.get('/seriales/traza/factura', {
          params: { tipo: facTipo, punto_venta: facPV.trim(), nro_documento: facNro.trim() },
        });
        data = res.data;
      } else if (modo === 'cliente') {
        if (!query.trim()) return;
        const res = await api.get(`/seriales/traza/cliente/${encodeURIComponent(query.trim())}`, {
          params: { page: currentPage, page_size: pageSize },
        });
        data = res.data;
      } else if (modo === 'dni') {
        if (!query.trim()) return;
        const res = await api.get(`/seriales/traza/cliente-dni/${encodeURIComponent(query.trim())}`, {
          params: { page: currentPage, page_size: pageSize },
        });
        data = res.data;
      } else if (modo === 'ml_user') {
        if (!query.trim()) return;
        const res = await api.get(`/seriales/traza/cliente-ml/${encodeURIComponent(query.trim())}`, {
          params: { page: currentPage, page_size: pageSize },
        });
        data = res.data;
      }
      setResult(data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(detail || 'No se encontraron resultados');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      setPage(1);
      buscar(1);
    }
  };

  const handleBuscar = () => {
    setPage(1);
    buscar(1);
  };

  const handlePageChange = (newPage) => {
    setPage(newPage);
    buscar(newPage);
  };

  const limpiar = () => {
    setQuery('');
    setFacTipo('A');
    setFacPV('');
    setFacNro('');
    setResult(null);
    setError(null);
    setPage(1);
  };

  const currentModo = MODOS.find((m) => m.id === modo);
  const isClienteMode = MODOS_CLIENTE.has(modo);

  // Group modes for rendering
  const productoModos = MODOS.filter((m) => m.group === 'producto');
  const clienteModos = MODOS.filter((m) => m.group === 'cliente');

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Traza</h1>
        <p className={styles.subtitle}>
          Consulta el historial completo por serial, venta ML, factura, o cliente
        </p>
      </div>

      {/* Search bar */}
      <div className={styles.searchSection}>
        {/* Mode selector */}
        <div className={styles.modeSelectorRow}>
          <div className={styles.modeGroup}>
            {productoModos.map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.id}
                  className={`${styles.modeBtn} ${modo === m.id ? styles.modeBtnActive : ''}`}
                  onClick={() => { setModo(m.id); setResult(null); setError(null); setPage(1); }}
                >
                  <Icon size={14} />
                  {m.label}
                </button>
              );
            })}
          </div>
          <span className={styles.modeDivider} />
          <div className={styles.modeGroup}>
            {clienteModos.map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.id}
                  className={`${styles.modeBtn} ${modo === m.id ? styles.modeBtnActive : ''}`}
                  onClick={() => { setModo(m.id); setResult(null); setError(null); setPage(1); }}
                >
                  <Icon size={14} />
                  {m.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Input fields */}
        <div className={styles.inputRow}>
          {modo !== 'factura' ? (
            <div className={styles.inputWrapper}>
              <Search size={14} className={styles.inputIcon} />
              <input
                type="text"
                className="input-tesla"
                placeholder={currentModo?.placeholder}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                style={{ paddingLeft: '36px', width: '100%' }}
              />
            </div>
          ) : (
            <div className={styles.facturaInputs}>
              <select
                className="select-tesla"
                value={facTipo}
                onChange={(e) => setFacTipo(e.target.value)}
                style={{ width: '80px' }}
              >
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="E">E</option>
                <option value="M">M</option>
                <option value="X">X</option>
              </select>
              <input
                type="text"
                className="input-tesla"
                placeholder="Punto de venta"
                value={facPV}
                onChange={(e) => setFacPV(e.target.value)}
                onKeyDown={handleKeyDown}
                style={{ width: '120px' }}
              />
              <input
                type="text"
                className="input-tesla"
                placeholder="Nro documento"
                value={facNro}
                onChange={(e) => setFacNro(e.target.value)}
                onKeyDown={handleKeyDown}
                style={{ flex: 1 }}
              />
            </div>
          )}

          <button
            className="btn-tesla outline-subtle-primary"
            onClick={handleBuscar}
            disabled={loading}
          >
            <Search size={14} />
            {loading ? 'Buscando...' : 'Buscar'}
          </button>

          {(result || error) && (
            <button className="btn-tesla ghost" onClick={limpiar}>
              Limpiar
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className={styles.errorMsg}>{error}</div>
      )}

      {/* Results */}
      {result && (
        <div className={styles.resultsSection}>
          {isClienteMode ? (
            <TrazaClienteViewer
              data={result}
              page={page}
              pageSize={pageSize}
              onPageChange={handlePageChange}
            />
          ) : (
            <TrazaViewer data={result} variant={modo} />
          )}
        </div>
      )}

      {/* Empty state (initial) */}
      {!result && !error && !loading && (
        <div className={styles.emptyState}>
          <ScanBarcode size={48} strokeWidth={1} />
          <p>Ingresa un serial, ML ID, factura, o datos de cliente para consultar la traza</p>
        </div>
      )}
    </div>
  );
}
