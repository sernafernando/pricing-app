/**
 * RmaEnviosProveedor — Items RMA pendientes de envío a proveedor,
 * agrupados por proveedor. Cada grupo muestra datos de contacto,
 * dirección, y los items con falla/estado.
 *
 * Permite seleccionar items y crear un envío manual (EtiquetaEnvio)
 * que los vincula al shipping_id y los marca como enviados.
 *
 * Muestra alerta cuando la cantidad de items alcanza el mínimo
 * configurado en el proveedor (unidades_minimas_rma).
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Truck,
  Package,
  MapPin,
  Phone,
  Mail,
  User,
  Clock,
  AlertTriangle,
  RefreshCcw,
  ChevronDown,
  ChevronUp,
  Send,
  CheckSquare,
  Square,
  Loader,
} from 'lucide-react';
import api from '../services/api';
import styles from './RmaEnviosProveedor.module.css';

const todayStr = () => new Date().toISOString().split('T')[0];

export default function RmaEnviosProveedor() {
  const [grupos, setGrupos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  // Selection: { [supp_id]: Set<item_id> }
  const [selectedItems, setSelectedItems] = useState({});
  // Envío creation state per supplier: { [supp_id]: { loading, error, success } }
  const [envioState, setEnvioState] = useState({});

  const cargar = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/rma-seguimiento/envios-proveedor/pendientes');
      setGrupos(data);
      // Auto-expand all groups
      const expanded = {};
      for (const g of data) {
        expanded[g.supp_id] = true;
      }
      setExpandedGroups(expanded);
      // Reset selections (items changed)
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

  const toggleGroup = (suppId) => {
    setExpandedGroups((prev) => ({ ...prev, [suppId]: !prev[suppId] }));
  };

  // ── Selection helpers ──

  const getSelected = (suppId) => selectedItems[suppId] || new Set();

  const toggleItem = (suppId, itemId) => {
    setSelectedItems((prev) => {
      const current = new Set(prev[suppId] || []);
      if (current.has(itemId)) {
        current.delete(itemId);
      } else {
        current.add(itemId);
      }
      return { ...prev, [suppId]: current };
    });
  };

  const toggleAllInGroup = (suppId, items) => {
    setSelectedItems((prev) => {
      const current = new Set(prev[suppId] || []);
      const listos = items.filter((i) => i.listo_envio_proveedor);
      const allSelected = listos.length > 0 && listos.every((i) => current.has(i.id));
      if (allSelected) {
        // Deselect all
        return { ...prev, [suppId]: new Set() };
      }
      // Select all listos
      return { ...prev, [suppId]: new Set(listos.map((i) => i.id)) };
    });
  };

  // ── Crear envío ──

  const crearEnvio = async (suppId) => {
    const selected = getSelected(suppId);
    if (selected.size === 0) return;

    setEnvioState((prev) => ({ ...prev, [suppId]: { loading: true, error: null, success: null } }));
    try {
      const { data } = await api.post('/rma-seguimiento/envios-proveedor/crear-envio', {
        supp_id: suppId,
        item_ids: Array.from(selected),
        fecha_envio: todayStr(),
      });
      setEnvioState((prev) => ({ ...prev, [suppId]: { loading: false, error: null, success: data.mensaje } }));
      // Reload after short delay so user sees the success message
      setTimeout(() => cargar(), 1500);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al crear envío';
      setEnvioState((prev) => ({ ...prev, [suppId]: { loading: false, error: msg, success: null } }));
    }
  };

  const totalItems = grupos.reduce((sum, g) => sum + g.cantidad_items, 0);

  if (loading) {
    return <div className={styles.statusMsg}>Cargando items pendientes de envio...</div>;
  }

  if (error) {
    return <div className={styles.errorMsg}>{error}</div>;
  }

  if (grupos.length === 0) {
    return (
      <div className={styles.emptyState}>
        <Truck size={32} />
        <p>No hay items pendientes de envio a proveedor</p>
        <span>Los items aparecen aqui cuando tienen proveedor asignado y no fueron enviados</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.summaryBar}>
        <span className={styles.summaryText}>
          {totalItems} items pendientes en {grupos.length} proveedores
        </span>
        <button className="btn-tesla ghost sm" onClick={cargar} aria-label="Recargar">
          <RefreshCcw size={14} />
        </button>
      </div>

      {grupos.map((grupo) => {
        const prov = grupo.proveedor;
        const isExpanded = expandedGroups[grupo.supp_id];
        const minAlcanzado = prov.unidades_minimas_rma != null
          && grupo.cantidad_items >= prov.unidades_minimas_rma;
        const tieneDireccion = prov.direccion || prov.ciudad;
        const selected = getSelected(grupo.supp_id);
        const listosCount = grupo.items.filter((i) => i.listo_envio_proveedor).length;
        const state = envioState[grupo.supp_id] || {};

        return (
          <div key={grupo.supp_id} className={styles.group}>
            {/* Group header */}
            <button
              className={styles.groupHeader}
              onClick={() => toggleGroup(grupo.supp_id)}
              aria-expanded={isExpanded}
            >
              <div className={styles.groupTitle}>
                <Package size={16} />
                <span className={styles.provNombre}>{prov.nombre || grupo.proveedor_nombre}</span>
                <span className={styles.countBadge}>
                  {grupo.cantidad_items} items
                </span>
                {listosCount > 0 && (
                  <span className={styles.listoBadge}>
                    <CheckSquare size={12} />
                    {listosCount} listos
                  </span>
                )}
                {minAlcanzado && (
                  <span className={styles.alertaBadge} title={`Minimo ${prov.unidades_minimas_rma} unidades alcanzado`}>
                    <AlertTriangle size={12} />
                    Listo para enviar
                  </span>
                )}
                {prov.unidades_minimas_rma != null && !minAlcanzado && (
                  <span className={styles.minimoBadge}>
                    Min: {prov.unidades_minimas_rma}
                  </span>
                )}
              </div>
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>

            {/* Expanded content */}
            {isExpanded && (
              <div className={styles.groupBody}>
                {/* Supplier info bar */}
                {tieneDireccion && (
                  <div className={styles.provInfo}>
                    {prov.direccion && (
                      <span className={styles.infoItem}>
                        <MapPin size={13} /> {prov.direccion}{prov.ciudad ? `, ${prov.ciudad}` : ''}{prov.cp ? ` (${prov.cp})` : ''}
                      </span>
                    )}
                    {prov.telefono && (
                      <span className={styles.infoItem}>
                        <Phone size={13} /> {prov.telefono}
                      </span>
                    )}
                    {prov.email && (
                      <span className={styles.infoItem}>
                        <Mail size={13} /> {prov.email}
                      </span>
                    )}
                    {prov.representante && (
                      <span className={styles.infoItem}>
                        <User size={13} /> {prov.representante}
                      </span>
                    )}
                    {prov.horario && (
                      <span className={styles.infoItem}>
                        <Clock size={13} /> {prov.horario}
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
                            onClick={() => toggleAllInGroup(grupo.supp_id, grupo.items)}
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
                        <th>Estado Prov.</th>
                      </tr>
                    </thead>
                    <tbody className="table-tesla-body">
                      {grupo.items.map((item) => {
                        const isListo = item.listo_envio_proveedor;
                        const isSelected = selected.has(item.id);
                        return (
                          <tr
                            key={item.id}
                            className={isSelected ? styles.selectedRow : ''}
                            onClick={() => isListo && toggleItem(grupo.supp_id, item.id)}
                            style={isListo ? { cursor: 'pointer' } : undefined}
                          >
                            <td className={styles.cellCheck}>
                              {isListo ? (
                                <button
                                  className={styles.checkBtn}
                                  onClick={(e) => { e.stopPropagation(); toggleItem(grupo.supp_id, item.id); }}
                                  aria-label={isSelected ? 'Deseleccionar' : 'Seleccionar'}
                                >
                                  {isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                                </button>
                              ) : (
                                <span className={styles.notReady} title="Marcar como 'Listo para envio' en el caso">
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
                              {item.estado_proveedor_valor ? (
                                <span
                                  className={styles.badgeOpcion}
                                  style={{ '--badge-color': `var(--color-${item.estado_proveedor_color || 'gray'})` }}
                                >
                                  {item.estado_proveedor_valor}
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
                      onClick={() => crearEnvio(grupo.supp_id)}
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
