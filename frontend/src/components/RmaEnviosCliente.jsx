/**
 * RmaEnviosCliente — Items RMA pendientes de devolución al cliente,
 * agrupados por cliente. Cada grupo muestra datos de contacto,
 * dirección, y los items listos para enviar.
 *
 * Permite seleccionar items y crear un envío manual (EtiquetaEnvio)
 * que los vincula al shipping_cliente_id y los marca como enviados.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  PackageCheck,
  User,
  MapPin,
  Phone,
  Mail,
  Hash,
  RefreshCcw,
  ChevronDown,
  ChevronUp,
  Send,
  CheckSquare,
  Square,
  Loader,
} from 'lucide-react';
import api from '../services/api';
import styles from './RmaEnviosCliente.module.css';

const todayStr = () => new Date().toISOString().split('T')[0];

export default function RmaEnviosCliente() {
  const [grupos, setGrupos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  // Selection: { [cust_id]: Set<item_id> }
  const [selectedItems, setSelectedItems] = useState({});
  // Envío creation state per client: { [cust_id]: { loading, error, success } }
  const [envioState, setEnvioState] = useState({});

  const cargar = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/rma-seguimiento/envios-cliente/pendientes');
      setGrupos(data);
      // Auto-expand all groups
      const expanded = {};
      for (const g of data) {
        expanded[g.cust_id] = true;
      }
      setExpandedGroups(expanded);
      // Reset selections
      setSelectedItems({});
      setEnvioState({});
    } catch {
      setError('Error al cargar items pendientes');
      setGrupos([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const toggleGroup = (custId) => {
    setExpandedGroups((prev) => ({ ...prev, [custId]: !prev[custId] }));
  };

  // ── Selection helpers ──

  const getSelected = (custId) => selectedItems[custId] || new Set();

  const toggleItem = (custId, itemId) => {
    setSelectedItems((prev) => {
      const current = new Set(prev[custId] || []);
      if (current.has(itemId)) {
        current.delete(itemId);
      } else {
        current.add(itemId);
      }
      return { ...prev, [custId]: current };
    });
  };

  const toggleAllInGroup = (custId, items) => {
    setSelectedItems((prev) => {
      const current = new Set(prev[custId] || []);
      const listos = items.filter((i) => i.listo_envio_cliente);
      const allSelected = listos.length > 0 && listos.every((i) => current.has(i.id));
      if (allSelected) {
        return { ...prev, [custId]: new Set() };
      }
      return { ...prev, [custId]: new Set(listos.map((i) => i.id)) };
    });
  };

  // ── Crear envío ──

  const crearEnvio = async (custId) => {
    const selected = getSelected(custId);
    if (selected.size === 0) return;

    setEnvioState((prev) => ({ ...prev, [custId]: { loading: true, error: null, success: null } }));
    try {
      const { data } = await api.post('/rma-seguimiento/envios-cliente/crear-envio', {
        cust_id: custId,
        item_ids: Array.from(selected),
        fecha_envio: todayStr(),
      });
      setEnvioState((prev) => ({ ...prev, [custId]: { loading: false, error: null, success: data.mensaje } }));
      setTimeout(() => cargar(), 1500);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al crear envio';
      setEnvioState((prev) => ({ ...prev, [custId]: { loading: false, error: msg, success: null } }));
    }
  };

  const totalItems = grupos.reduce((sum, g) => sum + g.cantidad_items, 0);

  if (loading) {
    return <div className={styles.statusMsg}>Cargando items pendientes de envio a cliente...</div>;
  }

  if (error) {
    return <div className={styles.errorMsg}>{error}</div>;
  }

  if (grupos.length === 0) {
    return (
      <div className={styles.emptyState}>
        <PackageCheck size={32} />
        <p>No hay items pendientes de envio a cliente</p>
        <span>Los items aparecen aqui cuando se marcan como &quot;Listo para envio a cliente&quot; en el caso</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.summaryBar}>
        <span className={styles.summaryText}>
          {totalItems} items pendientes en {grupos.length} clientes
        </span>
        <button className="btn-tesla ghost sm" onClick={cargar} aria-label="Recargar">
          <RefreshCcw size={14} />
        </button>
      </div>

      {grupos.map((grupo) => {
        const cli = grupo.cliente;
        const isExpanded = expandedGroups[grupo.cust_id];
        const tieneDireccion = cli.direccion || cli.ciudad;
        const selected = getSelected(grupo.cust_id);
        const listosCount = grupo.items.filter((i) => i.listo_envio_cliente).length;
        const state = envioState[grupo.cust_id] || {};

        return (
          <div key={grupo.cust_id} className={styles.group}>
            {/* Group header */}
            <button
              className={styles.groupHeader}
              onClick={() => toggleGroup(grupo.cust_id)}
              aria-expanded={isExpanded}
            >
              <div className={styles.groupTitle}>
                <User size={16} />
                <span className={styles.clienteNombre}>{cli.nombre || grupo.cliente_nombre}</span>
                <span className={styles.countBadge}>
                  {grupo.cantidad_items} items
                </span>
                {listosCount > 0 && (
                  <span className={styles.listoBadge}>
                    <CheckSquare size={12} />
                    {listosCount} listos
                  </span>
                )}
              </div>
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>

            {/* Expanded content */}
            {isExpanded && (
              <div className={styles.groupBody}>
                {/* Client info bar */}
                {(tieneDireccion || cli.telefono || cli.celular || cli.email || cli.dni) && (
                  <div className={styles.clienteInfo}>
                    {tieneDireccion && (
                      <span className={styles.infoItem}>
                        <MapPin size={13} /> {cli.direccion || ''}{cli.ciudad ? `, ${cli.ciudad}` : ''}{cli.cp ? ` (${cli.cp})` : ''}
                      </span>
                    )}
                    {(cli.telefono || cli.celular) && (
                      <span className={styles.infoItem}>
                        <Phone size={13} /> {cli.telefono || cli.celular}
                      </span>
                    )}
                    {cli.email && (
                      <span className={styles.infoItem}>
                        <Mail size={13} /> {cli.email}
                      </span>
                    )}
                    {cli.dni && (
                      <span className={styles.infoItem}>
                        <Hash size={13} /> {cli.dni}
                      </span>
                    )}
                  </div>
                )}

                {/* Items table */}
                <div className="table-container-tesla">
                  <table className="table-tesla striped">
                    <thead className="table-tesla-head">
                      <tr>
                        <th className={styles.cellCheck}>
                          <button
                            className={styles.checkBtn}
                            onClick={() => toggleAllInGroup(grupo.cust_id, grupo.items)}
                            aria-label="Seleccionar todos los listos"
                            title="Seleccionar todos los marcados como listos"
                          >
                            {listosCount > 0 && selected.size === listosCount
                              ? <CheckSquare size={15} />
                              : <Square size={15} />}
                          </button>
                        </th>
                        <th>Caso</th>
                        <th>Serie</th>
                        <th>Producto</th>
                        <th>EAN</th>
                        <th>Falla</th>
                        <th>Estado</th>
                      </tr>
                    </thead>
                    <tbody className="table-tesla-body">
                      {grupo.items.map((item) => {
                        const isListo = item.listo_envio_cliente;
                        const isSelected = selected.has(item.id);
                        return (
                          <tr
                            key={item.id}
                            className={isSelected ? styles.selectedRow : ''}
                            onClick={() => isListo && toggleItem(grupo.cust_id, item.id)}
                            style={isListo ? { cursor: 'pointer' } : undefined}
                          >
                            <td className={styles.cellCheck}>
                              {isListo ? (
                                <button
                                  className={styles.checkBtn}
                                  onClick={(e) => { e.stopPropagation(); toggleItem(grupo.cust_id, item.id); }}
                                  aria-label={isSelected ? 'Deseleccionar' : 'Seleccionar'}
                                >
                                  {isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                                </button>
                              ) : (
                                <span className={styles.notReady} title="Marcar como 'Listo para envio a cliente' en el caso">
                                  <Square size={15} />
                                </span>
                              )}
                            </td>
                            <td className={styles.cellCaso}>{item.numero_caso}</td>
                            <td className={styles.cellMono}>{item.serial_number || '\u2014'}</td>
                            <td>{item.producto_desc || '\u2014'}</td>
                            <td className={styles.cellMono}>{item.ean || '\u2014'}</td>
                            <td className={styles.cellFalla}>
                              {item.descripcion_falla
                                ? item.descripcion_falla.substring(0, 80) + (item.descripcion_falla.length > 80 ? '...' : '')
                                : '\u2014'}
                            </td>
                            <td>
                              {item.estado_proceso_valor ? (
                                <span
                                  className={styles.badgeOpcion}
                                  style={{ '--badge-color': `var(--color-${item.estado_proceso_color || 'gray'})` }}
                                >
                                  {item.estado_proceso_valor}
                                </span>
                              ) : '\u2014'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Action bar */}
                <div className={styles.actionBar}>
                  {state.success && (
                    <span className={styles.successMsg}>{state.success}</span>
                  )}
                  {state.error && (
                    <span className={styles.errorInline}>{state.error}</span>
                  )}
                  <div className={styles.actionRight}>
                    {selected.size > 0 && (
                      <span className={styles.selectionCount}>
                        {selected.size} seleccionados
                      </span>
                    )}
                    <button
                      className="btn-tesla outline-subtle-primary sm"
                      disabled={selected.size === 0 || state.loading}
                      onClick={() => crearEnvio(grupo.cust_id)}
                    >
                      {state.loading
                        ? <><Loader size={14} className={styles.spinning} /> Creando...</>
                        : <><Send size={14} /> Crear Envio ({selected.size})</>}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
