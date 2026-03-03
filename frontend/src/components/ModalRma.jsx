/**
 * Modal de caso RMA - 7 tabs con todos los campos del ciclo de vida.
 *
 * Tabs: Info | Recepción | Revisión | Reclamo ML | Proveedor | Proceso | Historial
 *
 * - Caso nuevo: solo tab Info con búsqueda de traza
 * - Caso existente: todas las tabs, edición inline por item via PUT
 * - Campos caso-level se guardan con el botón Guardar
 * - Campos item-level se guardan inline (onChange → PUT)
 */

import { useState, useEffect } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla, { ModalSection, ModalFooterButtons, ModalLoading } from './ModalTesla';
import { Search, Plus, Trash2, ExternalLink, Clock, User } from 'lucide-react';

const labelStyle = { fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' };
const checkLabel = { display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' };
const grid2 = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' };
const grid3 = { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' };
const metaStyle = { marginTop: '8px', fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' };

export default function ModalRma({ caso, onClose }) {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const esNuevo = !caso;

  const [activeTab, setActiveTab] = useState('info');
  const [loading, setLoading] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [opciones, setOpciones] = useState({});
  const [casoData, setCasoData] = useState(caso || {});
  const [historial, setHistorial] = useState([]);

  // Búsqueda de traza para nuevo caso
  const [searchSerial, setSearchSerial] = useState('');
  const [trazaResult, setTrazaResult] = useState(null);
  const [buscandoTraza, setBuscandoTraza] = useState(false);

  useEffect(() => {
    cargarOpciones();
    if (caso?.id) {
      cargarCasoCompleto();
      cargarHistorial();
    }
  }, []);

  const cargarOpciones = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/opciones', { params: { solo_activas: true } });
      const grouped = {};
      for (const op of data) {
        if (!grouped[op.categoria]) grouped[op.categoria] = [];
        grouped[op.categoria].push(op);
      }
      setOpciones(grouped);
    } catch {
      // opciones vacías
    }
  };

  const cargarCasoCompleto = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/rma-seguimiento/${caso.id}`);
      setCasoData(data);
    } catch {
      // mantener datos existentes
    } finally {
      setLoading(false);
    }
  };

  const cargarHistorial = async () => {
    try {
      const { data } = await api.get(`/rma-seguimiento/${caso.id}/historial`);
      setHistorial(data);
    } catch {
      // historial vacío
    }
  };

  const buscarTraza = async () => {
    if (!searchSerial.trim()) return;
    setBuscandoTraza(true);
    setTrazaResult(null);
    try {
      let data;
      if (searchSerial.startsWith('2000')) {
        const res = await api.get(`/seriales/traza/ml/${searchSerial}`);
        data = res.data;
      } else {
        const res = await api.get(`/seriales/traza/${searchSerial}`);
        data = res.data;
      }
      setTrazaResult(data);
    } catch {
      setTrazaResult({ error: 'No se encontraron resultados' });
    } finally {
      setBuscandoTraza(false);
    }
  };

  const agregarItemDesdeTraza = (serial, articulo, pedido) => {
    const nuevoItem = {
      serial_number: serial || null,
      item_id: articulo?.item_id || null,
      ean: null,
      producto_desc: articulo?.descripcion || 'Sin descripción',
      precio: null,
      link_ml: pedido?.ml_id ? `https://www.mercadolibre.com.ar/ventas/${pedido.ml_id}/detalle` : null,
    };

    setCasoData((prev) => ({
      ...prev,
      items: [...(prev.items || []), nuevoItem],
      ml_id: prev.ml_id || pedido?.ml_id || null,
      cliente_nombre: prev.cliente_nombre || pedido?.cliente || null,
    }));
  };

  const handleGuardar = async () => {
    setGuardando(true);
    try {
      if (esNuevo) {
        await api.post('/rma-seguimiento', {
          cust_id: casoData.cust_id,
          cliente_nombre: casoData.cliente_nombre,
          cliente_dni: casoData.cliente_dni,
          cliente_numero: casoData.cliente_numero,
          ml_id: casoData.ml_id,
          origen: casoData.origen,
          items: (casoData.items || []).map((i) => ({
            serial_number: i.serial_number,
            item_id: i.item_id,
            is_id: i.is_id,
            it_transaction: i.it_transaction,
            ean: i.ean,
            producto_desc: i.producto_desc,
            precio: i.precio,
            estado_facturacion: i.estado_facturacion,
            link_ml: i.link_ml,
          })),
        });
      } else {
        await api.put(`/rma-seguimiento/${caso.id}`, {
          estado: casoData.estado,
          marcado_borrar_pedido: casoData.marcado_borrar_pedido,
          estado_reclamo_ml_id: casoData.estado_reclamo_ml_id,
          cobertura_ml_id: casoData.cobertura_ml_id,
          monto_cubierto: casoData.monto_cubierto,
          observaciones: casoData.observaciones,
          corroborar_nc: casoData.corroborar_nc,
        });
      }
      onClose(true);
    } catch {
      // error feedback
    } finally {
      setGuardando(false);
    }
  };

  const handleItemUpdate = async (itemId, field, value) => {
    if (!caso?.id) return;
    try {
      const { data } = await api.put(`/rma-seguimiento/${caso.id}/items/${itemId}`, { [field]: value });
      setCasoData((prev) => ({
        ...prev,
        items: prev.items.map((i) => (i.id === itemId ? data : i)),
      }));
    } catch {
      // error
    }
  };

  const renderDropdown = (categoria, value, onChange, disabled = false) => {
    const opts = opciones[categoria] || [];
    return (
      <select value={value || ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} disabled={disabled} className="select-tesla">
        <option value="">— Seleccionar —</option>
        {opts.map((op) => (
          <option key={op.id} value={op.id}>{op.valor}</option>
        ))}
      </select>
    );
  };

  const renderItemMeta = (item, tipoUsuario, tipoFecha) => {
    const userId = item[tipoUsuario];
    const fecha = item[tipoFecha];
    if (!fecha) return null;
    return (
      <div style={metaStyle}>
        <User size={12} /> Usuario #{userId} <Clock size={12} /> {new Date(fecha).toLocaleString('es-AR')}
      </div>
    );
  };

  const tabs = [
    { id: 'info', label: 'Información' },
    ...(esNuevo ? [] : [
      { id: 'recepcion', label: 'Recepción' },
      { id: 'revision', label: 'Revisión' },
      { id: 'reclamo', label: 'Reclamo ML' },
      { id: 'proveedor', label: 'Proveedor' },
      { id: 'proceso', label: 'Proceso' },
      { id: 'historial', label: 'Historial', badge: historial.length || undefined },
    ]),
  ];

  return (
    <ModalTesla
      isOpen={true}
      onClose={() => onClose(false)}
      title={esNuevo ? 'Nuevo Caso RMA' : `Caso ${casoData.numero_caso || ''}`}
      subtitle={casoData.cliente_nombre || 'Sin cliente'}
      size="xl"
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      footer={
        puedeGestionar && (
          <ModalFooterButtons
            onCancel={() => onClose(false)}
            onConfirm={handleGuardar}
            confirmText={esNuevo ? 'Crear Caso' : 'Guardar'}
            confirmLoading={guardando}
          />
        )
      }
    >
      {loading ? <ModalLoading message="Cargando caso..." /> : (
        <>
          {/* ═══════════ TAB: Información ═══════════ */}
          {activeTab === 'info' && (
            <div>
              {/* Búsqueda de traza (solo nuevo) */}
              {esNuevo && (
                <ModalSection title="Buscar artículo por serie o ML ID">
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                    <div style={{ flex: 1, display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        placeholder="Ingresar serie o ID de venta ML..."
                        value={searchSerial}
                        onChange={(e) => setSearchSerial(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && buscarTraza()}
                        className="input-tesla"
                        style={{ flex: 1 }}
                      />
                      <button className="btn-tesla outline-subtle-primary sm" onClick={buscarTraza} disabled={buscandoTraza}>
                        <Search size={14} /> {buscandoTraza ? 'Buscando...' : 'Buscar'}
                      </button>
                    </div>
                  </div>

                  {trazaResult && !trazaResult.error && (
                    <div style={{ background: 'var(--bg-tertiary)', borderRadius: '8px', padding: '12px', marginBottom: '12px' }}>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Resultados de traza:</p>
                      {trazaResult.articulo && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px', background: 'var(--bg-secondary)', borderRadius: '6px' }}>
                          <div>
                            <strong>{trazaResult.articulo.descripcion}</strong>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              {trazaResult.serial} — {trazaResult.articulo.codigo}
                            </div>
                          </div>
                          <button className="btn-tesla outline-subtle-success sm" onClick={() => agregarItemDesdeTraza(trazaResult.serial, trazaResult.articulo, trazaResult.pedidos?.[0])}>
                            <Plus size={14} /> Agregar
                          </button>
                        </div>
                      )}
                      {trazaResult.seriales?.map((s, idx) => (
                        <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px', background: 'var(--bg-secondary)', borderRadius: '6px', marginTop: '4px' }}>
                          <div>
                            <strong>{s.articulo?.descripcion || 'Sin descripción'}</strong>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{s.serial}</div>
                          </div>
                          <button className="btn-tesla outline-subtle-success sm" onClick={() => agregarItemDesdeTraza(s.serial, s.articulo, trazaResult.pedidos?.[0])}>
                            <Plus size={14} /> Agregar
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {trazaResult?.error && (
                    <p style={{ color: 'var(--color-danger)', fontSize: '0.85rem' }}>{trazaResult.error}</p>
                  )}
                </ModalSection>
              )}

              {/* Datos del caso */}
              <ModalSection title="Datos del caso">
                <div style={grid2}>
                  <label>
                    <span style={labelStyle}>Cliente</span>
                    <input className="input-tesla" value={casoData.cliente_nombre || ''} onChange={(e) => setCasoData({ ...casoData, cliente_nombre: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span style={labelStyle}>DNI</span>
                    <input className="input-tesla" value={casoData.cliente_dni || ''} onChange={(e) => setCasoData({ ...casoData, cliente_dni: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span style={labelStyle}>ML ID</span>
                    <input className="input-tesla" value={casoData.ml_id || ''} onChange={(e) => setCasoData({ ...casoData, ml_id: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span style={labelStyle}>Origen</span>
                    <select className="select-tesla" value={casoData.origen || ''} onChange={(e) => setCasoData({ ...casoData, origen: e.target.value })} disabled={!puedeGestionar}>
                      <option value="">— Seleccionar —</option>
                      <option value="mercadolibre">MercadoLibre</option>
                      <option value="tienda_nube">Tienda Nube</option>
                      <option value="mostrador">Mostrador</option>
                    </select>
                  </label>
                </div>
              </ModalSection>

              {/* Items */}
              <ModalSection title={`Artículos (${(casoData.items || []).length})`}>
                {(casoData.items || []).length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No hay artículos. Usá la búsqueda de traza para agregar.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {(casoData.items || []).map((item, idx) => (
                      <div key={item.id || idx} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px', background: 'var(--bg-tertiary)', borderRadius: '8px' }}>
                        <div style={{ flex: 1 }}>
                          <strong style={{ fontSize: '0.85rem' }}>{item.producto_desc || '—'}</strong>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', gap: '12px', marginTop: '2px' }}>
                            {item.serial_number && <span>S/N: {item.serial_number}</span>}
                            {item.precio && <span>${Number(item.precio).toLocaleString('es-AR')}</span>}
                            {item.estado_facturacion && <span>{item.estado_facturacion}</span>}
                          </div>
                        </div>
                        {item.link_ml && (
                          <a href={item.link_ml} target="_blank" rel="noopener noreferrer" className="btn-tesla ghost sm" title="Ver en ML">
                            <ExternalLink size={14} />
                          </a>
                        )}
                        {esNuevo && (
                          <button className="btn-tesla ghost sm" onClick={() => setCasoData((prev) => ({ ...prev, items: prev.items.filter((_, i) => i !== idx) }))} title="Quitar" aria-label="Quitar artículo">
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </ModalSection>

              {/* Campos caso-level (solo edición) */}
              {!esNuevo && (
                <>
                  <ModalSection title="Estado del caso">
                    <div style={grid2}>
                      <label>
                        <span style={labelStyle}>Estado del caso</span>
                        <select className="select-tesla" value={casoData.estado || 'abierto'} onChange={(e) => setCasoData({ ...casoData, estado: e.target.value })} disabled={!puedeGestionar}>
                          <option value="abierto">Abierto</option>
                          <option value="en_espera">En espera</option>
                          <option value="cerrado">Cerrado</option>
                        </select>
                      </label>
                      <label style={{ ...checkLabel, paddingTop: '20px' }}>
                        <input type="checkbox" checked={casoData.marcado_borrar_pedido || false} onChange={(e) => setCasoData({ ...casoData, marcado_borrar_pedido: e.target.checked })} disabled={!puedeGestionar} />
                        Marcado para borrar pedido
                      </label>
                    </div>
                  </ModalSection>

                  <ModalSection title="Observaciones">
                    <textarea
                      className="input-tesla"
                      rows={3}
                      value={casoData.observaciones || ''}
                      onChange={(e) => setCasoData({ ...casoData, observaciones: e.target.value })}
                      placeholder="Observaciones generales del caso..."
                      disabled={!puedeGestionar}
                      style={{ width: '100%', resize: 'vertical' }}
                    />
                  </ModalSection>

                  <ModalSection title="Auditoría">
                    <div style={grid2}>
                      <label>
                        <span style={labelStyle}>Corroborar NC</span>
                        <input className="input-tesla" value={casoData.corroborar_nc || ''} onChange={(e) => setCasoData({ ...casoData, corroborar_nc: e.target.value })} disabled={!puedeGestionar} />
                      </label>
                      <div>
                        <span style={labelStyle}>Fecha</span>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{casoData.fecha_caso || '—'}</span>
                      </div>
                    </div>
                  </ModalSection>
                </>
              )}
            </div>
          )}

          {/* ═══════════ TAB: Recepción ═══════════ */}
          {activeTab === 'recepcion' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div style={grid3}>
                    <label>
                      <span style={labelStyle}>Estado de recepción</span>
                      {renderDropdown('estado_recepcion', item.estado_recepcion_id, (v) => handleItemUpdate(item.id, 'estado_recepcion_id', v), !puedeGestionar)}
                    </label>
                    <label>
                      <span style={labelStyle}>Costo de envío</span>
                      <input className="input-tesla" type="number" step="0.01" value={item.costo_envio || ''} onChange={(e) => handleItemUpdate(item.id, 'costo_envio', e.target.value ? Number(e.target.value) : null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span style={labelStyle}>Causa de devolución</span>
                      {renderDropdown('causa_devolucion', item.causa_devolucion_id, (v) => handleItemUpdate(item.id, 'causa_devolucion_id', v), !puedeGestionar)}
                    </label>
                  </div>
                  {renderItemMeta(item, 'recepcion_usuario_id', 'recepcion_fecha')}
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Revisión ═══════════ */}
          {activeTab === 'revision' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div style={grid3}>
                    <label>
                      <span style={labelStyle}>Apto para la venta</span>
                      {renderDropdown('apto_venta', item.apto_venta_id, (v) => handleItemUpdate(item.id, 'apto_venta_id', v), !puedeGestionar)}
                    </label>
                    <label style={{ ...checkLabel, paddingTop: '18px' }}>
                      <input type="checkbox" checked={item.requirio_reacondicionamiento || false} onChange={(e) => handleItemUpdate(item.id, 'requirio_reacondicionamiento', e.target.checked)} disabled={!puedeGestionar} />
                      Requirió reacondicionamiento
                    </label>
                    <label>
                      <span style={labelStyle}>Estado (ERP)</span>
                      {renderDropdown('estado_revision', item.estado_revision_id, (v) => handleItemUpdate(item.id, 'estado_revision_id', v), !puedeGestionar)}
                    </label>
                  </div>
                  {renderItemMeta(item, 'revision_usuario_id', 'revision_fecha')}
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Reclamo ML ═══════════ */}
          {activeTab === 'reclamo' && (
            <ModalSection title="Reclamo MercadoLibre">
              <div style={grid3}>
                <label>
                  <span style={labelStyle}>Estado del reclamo</span>
                  {renderDropdown('estado_reclamo_ml', casoData.estado_reclamo_ml_id, (v) => setCasoData({ ...casoData, estado_reclamo_ml_id: v }), !puedeGestionar)}
                </label>
                <label>
                  <span style={labelStyle}>ML cubrió el producto</span>
                  {renderDropdown('cobertura_ml', casoData.cobertura_ml_id, (v) => setCasoData({ ...casoData, cobertura_ml_id: v }), !puedeGestionar)}
                </label>
                <label>
                  <span style={labelStyle}>Monto cubierto</span>
                  <input className="input-tesla" type="number" step="0.01" value={casoData.monto_cubierto || ''} onChange={(e) => setCasoData({ ...casoData, monto_cubierto: e.target.value ? Number(e.target.value) : null })} disabled={!puedeGestionar} />
                </label>
              </div>
            </ModalSection>
          )}

          {/* ═══════════ TAB: Proveedor ═══════════ */}
          {activeTab === 'proveedor' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div style={grid2}>
                    <label>
                      <span style={labelStyle}>Proveedor</span>
                      <input className="input-tesla" value={item.proveedor_nombre || ''} onChange={(e) => handleItemUpdate(item.id, 'proveedor_nombre', e.target.value)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span style={labelStyle}>Estado proveedor</span>
                      {renderDropdown('estado_proveedor', item.estado_proveedor_id, (v) => handleItemUpdate(item.id, 'estado_proveedor_id', v), !puedeGestionar)}
                    </label>
                    <label style={checkLabel}>
                      <input type="checkbox" checked={item.enviado_proveedor || false} onChange={(e) => handleItemUpdate(item.id, 'enviado_proveedor', e.target.checked)} disabled={!puedeGestionar} />
                      Enviado a proveedor
                    </label>
                    <label>
                      <span style={labelStyle}>NC Proveedor</span>
                      <input className="input-tesla" value={item.nc_proveedor || ''} onChange={(e) => handleItemUpdate(item.id, 'nc_proveedor', e.target.value)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span style={labelStyle}>Monto NC Proveedor</span>
                      <input className="input-tesla" type="number" step="0.01" value={item.monto_nc_proveedor || ''} onChange={(e) => handleItemUpdate(item.id, 'monto_nc_proveedor', e.target.value ? Number(e.target.value) : null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span style={labelStyle}>Fecha envío</span>
                      <input className="input-tesla" type="date" value={item.fecha_envio_proveedor ? item.fecha_envio_proveedor.split('T')[0] : ''} onChange={(e) => handleItemUpdate(item.id, 'fecha_envio_proveedor', e.target.value || null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span style={labelStyle}>Fecha respuesta</span>
                      <input className="input-tesla" type="date" value={item.fecha_respuesta_proveedor ? item.fecha_respuesta_proveedor.split('T')[0] : ''} onChange={(e) => handleItemUpdate(item.id, 'fecha_respuesta_proveedor', e.target.value || null)} disabled={!puedeGestionar} />
                    </label>
                  </div>
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Proceso ═══════════ */}
          {activeTab === 'proceso' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div style={grid3}>
                    <label>
                      <span style={labelStyle}>Estado proceso</span>
                      {renderDropdown('estado_proceso', item.estado_proceso_id, (v) => handleItemUpdate(item.id, 'estado_proceso_id', v), !puedeGestionar)}
                    </label>
                    <label>
                      <span style={labelStyle}>Depósito destino</span>
                      {renderDropdown('deposito_destino', item.deposito_destino_id, (v) => handleItemUpdate(item.id, 'deposito_destino_id', v), !puedeGestionar)}
                    </label>
                    <label style={{ ...checkLabel, paddingTop: '18px' }}>
                      <input type="checkbox" checked={item.enviado_fisicamente_deposito || false} onChange={(e) => handleItemUpdate(item.id, 'enviado_fisicamente_deposito', e.target.checked)} disabled={!puedeGestionar} />
                      Enviado físicamente
                    </label>
                  </div>
                  <div style={{ ...grid3, marginTop: '12px' }}>
                    <label style={checkLabel}>
                      <input type="checkbox" checked={item.corroborar_nc || false} onChange={(e) => handleItemUpdate(item.id, 'corroborar_nc', e.target.checked)} disabled={!puedeGestionar} />
                      Corroborar NC
                    </label>
                    <label style={checkLabel}>
                      <input type="checkbox" checked={item.requirio_rma_interno || false} onChange={(e) => handleItemUpdate(item.id, 'requirio_rma_interno', e.target.checked)} disabled={!puedeGestionar} />
                      Requirió RMA Interno
                    </label>
                    <label style={checkLabel}>
                      <input type="checkbox" checked={item.requiere_nota_credito || false} onChange={(e) => handleItemUpdate(item.id, 'requiere_nota_credito', e.target.checked)} disabled={!puedeGestionar} />
                      Requiere nota de crédito
                    </label>
                  </div>
                  <div style={{ ...grid2, marginTop: '12px' }}>
                    <label style={checkLabel}>
                      <input type="checkbox" checked={item.debe_facturarse || false} onChange={(e) => handleItemUpdate(item.id, 'debe_facturarse', e.target.checked)} disabled={!puedeGestionar} />
                      Otros items deben facturarse
                    </label>
                    <label>
                      <span style={labelStyle}>Observaciones</span>
                      <textarea
                        className="input-tesla"
                        rows={2}
                        value={item.observaciones || ''}
                        onChange={(e) => handleItemUpdate(item.id, 'observaciones', e.target.value)}
                        placeholder="Observaciones del artículo..."
                        disabled={!puedeGestionar}
                        style={{ width: '100%', resize: 'vertical' }}
                      />
                    </label>
                  </div>
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Historial ═══════════ */}
          {activeTab === 'historial' && (
            <div>
              {historial.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '24px' }}>Sin cambios registrados</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {historial.map((h) => (
                    <div key={h.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 12px', background: 'var(--bg-tertiary)', borderRadius: '6px', fontSize: '0.8rem' }}>
                      <Clock size={12} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                      <span style={{ color: 'var(--text-secondary)', minWidth: '130px' }}>
                        {h.created_at ? new Date(h.created_at).toLocaleString('es-AR') : '—'}
                      </span>
                      <strong style={{ minWidth: '80px' }}>{h.usuario_nombre || `#${h.usuario_id}`}</strong>
                      <span style={{ color: 'var(--text-secondary)' }}>{h.campo}:</span>
                      {h.valor_anterior && <span style={{ textDecoration: 'line-through', color: 'var(--color-danger)' }}>{h.valor_anterior}</span>}
                      <span style={{ color: 'var(--color-success)' }}>{h.valor_nuevo}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </ModalTesla>
  );
}
