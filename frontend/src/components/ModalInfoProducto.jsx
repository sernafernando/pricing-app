import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/ModalInfoProducto.css';
import { useModalClickOutside } from '../hooks/useModalClickOutside';

const ModalInfoProducto = ({ isOpen, onClose, itemId }) => {
  const { overlayRef, handleOverlayMouseDown, handleOverlayClick } = useModalClickOutside(onClose);
  const [detalle, setDetalle] = useState(null);
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    if (isOpen && itemId) {
      cargarDetalle();
    }
  }, [isOpen, itemId]);

  const cargarDetalle = async () => {
    setCargando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/detalle`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setDetalle(response.data);
    } catch (error) {
      console.error('Error cargando detalle:', error);
      alert('Error al cargar información del producto');
    } finally {
      setCargando(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  // Agregar listener global cuando el modal está abierto
  useEffect(() => {
    if (!isOpen) return;

    const handleGlobalKeyDown = (e) => {
      // ESC: cerrar modal
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }

      // BLOQUEAR todas las teclas para que no lleguen a la página de fondo
      e.stopPropagation();
    };

    // Usar capture phase (true) para capturar ANTES que el listener de la página
    window.addEventListener('keydown', handleGlobalKeyDown, true);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown, true);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const getMarkupColor = (markup) => {
    if (!markup) return 'var(--text-secondary)';
    const valor = parseFloat(markup);
    if (valor >= 30) return '#22c55e';
    if (valor >= 15) return '#f59e0b';
    return '#ef4444';
  };

  return (
    <div
      ref={overlayRef}
      className="modal-overlay"
      onMouseDown={handleOverlayMouseDown}
      onClick={handleOverlayClick}
      onKeyDown={handleKeyDown}
    >
      <div className="modal-info-producto" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Información Detallada</h2>
          <button onClick={onClose} className="close-btn">✕</button>
        </div>

        <div className="modal-body">
          {cargando ? (
            <p>Cargando...</p>
          ) : detalle ? (
            <>
              {/* INFORMACIÓN BÁSICA */}
              <section className="info-section">
                <h3>📦 Información Básica</h3>
                <div className="info-grid">
                  <div className="info-item">
                    <span className="info-label">Item ID:</span>
                    <span className="info-value">{detalle.producto.item_id}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Código:</span>
                    <span className="info-value">{detalle.producto.codigo}</span>
                  </div>
                  <div className="info-item full-width">
                    <span className="info-label">Descripción:</span>
                    <span className="info-value">{detalle.producto.descripcion}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Marca:</span>
                    <span className="info-value">{detalle.producto.marca || '-'}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Categoría:</span>
                    <span className="info-value">{detalle.producto.categoria || '-'}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Stock:</span>
                    <span className="info-value">{detalle.producto.stock}</span>
                  </div>
                </div>
              </section>

              {/* COSTOS */}
              <section className="info-section">
                <h3>💰 Costos</h3>
                <div className="info-grid">
                  <div className="info-item">
                    <span className="info-label">Costo ({detalle.producto.moneda_costo}):</span>
                    <span className="info-value highlight">
                      ${detalle.producto.costo.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  {detalle.producto.moneda_costo === 'USD' && (
                    <>
                      <div className="info-item">
                        <span className="info-label">Tipo de Cambio:</span>
                        <span className="info-value">
                          ${detalle.producto.tipo_cambio_usado?.toLocaleString('es-AR', { minimumFractionDigits: 2 }) || '-'}
                        </span>
                      </div>
                      <div className="info-item">
                        <span className="info-label">Costo ARS:</span>
                        <span className="info-value highlight">
                          ${detalle.producto.costo_ars.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                        </span>
                      </div>
                    </>
                  )}
                  <div className="info-item">
                    <span className="info-label">IVA:</span>
                    <span className="info-value">{detalle.producto.iva}%</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Costo Envío:</span>
                    <span className="info-value">
                      ${detalle.producto.costo_envio.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>
              </section>

              {/* PRICING - LISTA CLÁSICA */}
              <section className="info-section">
                <h3>💵 Pricing - Lista Clásica</h3>
                <div className="info-grid">
                  <div className="info-item">
                    <span className="info-label">Comisión ML:</span>
                    <span className="info-value">
                      {detalle.pricing.comision_ml_porcentaje ? `${detalle.pricing.comision_ml_porcentaje}%` : '-'}
                    </span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Precio:</span>
                    <span className="info-value highlight">
                      {detalle.pricing.precio_lista_ml
                        ? `$${detalle.pricing.precio_lista_ml.toLocaleString('es-AR', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">Markup:</span>
                    <span
                      className="info-value"
                      style={{
                        color: getMarkupColor(detalle.pricing.markup),
                        fontWeight: 'bold'
                      }}
                    >
                      {detalle.pricing.markup ? `${detalle.pricing.markup.toFixed(2)}%` : '-'}
                    </span>
                  </div>
                </div>
              </section>

              {/* CUOTAS */}
              {(detalle.pricing.precio_3_cuotas || detalle.pricing.precio_6_cuotas ||
                detalle.pricing.precio_9_cuotas || detalle.pricing.precio_12_cuotas) && (
                <section className="info-section">
                  <h3>📅 Precios con Cuotas</h3>
                  <div className="info-grid">
                    {detalle.pricing.precio_3_cuotas && (
                      <>
                        <div className="info-item">
                          <span className="info-label">3 Cuotas:</span>
                          <span className="info-value">
                            ${detalle.pricing.precio_3_cuotas.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                        <div className="info-item">
                          <span className="info-label">Markup 3c:</span>
                          <span
                            className="info-value"
                            style={{ color: getMarkupColor(detalle.pricing.markup_3_cuotas), fontWeight: 'bold' }}
                          >
                            {detalle.pricing.markup_3_cuotas?.toFixed(2)}%
                          </span>
                        </div>
                      </>
                    )}
                    {detalle.pricing.precio_6_cuotas && (
                      <>
                        <div className="info-item">
                          <span className="info-label">6 Cuotas:</span>
                          <span className="info-value">
                            ${detalle.pricing.precio_6_cuotas.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                        <div className="info-item">
                          <span className="info-label">Markup 6c:</span>
                          <span
                            className="info-value"
                            style={{ color: getMarkupColor(detalle.pricing.markup_6_cuotas), fontWeight: 'bold' }}
                          >
                            {detalle.pricing.markup_6_cuotas?.toFixed(2)}%
                          </span>
                        </div>
                      </>
                    )}
                    {detalle.pricing.precio_9_cuotas && (
                      <>
                        <div className="info-item">
                          <span className="info-label">9 Cuotas:</span>
                          <span className="info-value">
                            ${detalle.pricing.precio_9_cuotas.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                        <div className="info-item">
                          <span className="info-label">Markup 9c:</span>
                          <span
                            className="info-value"
                            style={{ color: getMarkupColor(detalle.pricing.markup_9_cuotas), fontWeight: 'bold' }}
                          >
                            {detalle.pricing.markup_9_cuotas?.toFixed(2)}%
                          </span>
                        </div>
                      </>
                    )}
                    {detalle.pricing.precio_12_cuotas && (
                      <>
                        <div className="info-item">
                          <span className="info-label">12 Cuotas:</span>
                          <span className="info-value">
                            ${detalle.pricing.precio_12_cuotas.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                        <div className="info-item">
                          <span className="info-label">Markup 12c:</span>
                          <span
                            className="info-value"
                            style={{ color: getMarkupColor(detalle.pricing.markup_12_cuotas), fontWeight: 'bold' }}
                          >
                            {detalle.pricing.markup_12_cuotas?.toFixed(2)}%
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                </section>
              )}

              {/* REBATE */}
              {detalle.pricing.participa_rebate && (
                <section className="info-section">
                  <h3>🎁 Rebate</h3>
                  <div className="info-grid">
                    <div className="info-item">
                      <span className="info-label">% Rebate:</span>
                      <span className="info-value">{detalle.pricing.porcentaje_rebate}%</span>
                    </div>
                    <div className="info-item">
                      <span className="info-label">Precio Rebate:</span>
                      <span className="info-value">
                        ${detalle.pricing.precio_rebate?.toLocaleString('es-AR', { minimumFractionDigits: 2 }) || '-'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="info-label">Markup Rebate:</span>
                      <span
                        className="info-value"
                        style={{ color: getMarkupColor(detalle.pricing.markup_rebate), fontWeight: 'bold' }}
                      >
                        {detalle.pricing.markup_rebate?.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </section>
              )}

              {/* WEB TRANSFERENCIA */}
              {detalle.pricing.participa_web_transferencia && (
                <section className="info-section">
                  <h3>💳 Web Transferencia</h3>
                  <div className="info-grid">
                    <div className="info-item">
                      <span className="info-label">% Markup Web:</span>
                      <span className="info-value">{detalle.pricing.porcentaje_markup_web}%</span>
                    </div>
                    <div className="info-item">
                      <span className="info-label">Precio Web:</span>
                      <span className="info-value">
                        ${detalle.pricing.precio_web_transferencia?.toLocaleString('es-AR', { minimumFractionDigits: 2 }) || '-'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="info-label">Markup Real:</span>
                      <span
                        className="info-value"
                        style={{ color: getMarkupColor(detalle.pricing.markup_web_real), fontWeight: 'bold' }}
                      >
                        {detalle.pricing.markup_web_real?.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </section>
              )}

              {/* PUBLICACIONES ML */}
              {detalle.publicaciones_ml && detalle.publicaciones_ml.length > 0 && (
                <section className="info-section">
                  <h3>📢 Publicaciones en Mercado Libre</h3>
                  <div className="publicaciones-table">
                    <table>
                      <thead>
                        <tr>
                          <th>MLA</th>
                          <th>Lista</th>
                          <th>Precio ML</th>
                          <th>Catálogo</th>
                          <th>Info Competencia</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detalle.publicaciones_ml.map((pub, idx) => (
                          <tr key={idx}>
                            <td>
                              <a
                                href={`https://articulo.mercadolibre.com.ar/${pub.mla}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: '#3b82f6', textDecoration: 'none' }}
                              >
                                {pub.mla}
                              </a>
                            </td>
                            <td>{pub.lista_nombre || '-'}</td>
                            <td>
                              {pub.precio_ml ? `$${pub.precio_ml.toLocaleString('es-AR', { minimumFractionDigits: 2 })}` : '-'}
                            </td>
                            <td>
                              {pub.catalog_product_id && pub.catalog_status ? (
                                <span
                                  style={{
                                    padding: '4px 8px',
                                    borderRadius: '4px',
                                    fontSize: '11px',
                                    fontWeight: '600',
                                    backgroundColor:
                                      pub.catalog_status === 'winning' ? '#22c55e' :
                                      pub.catalog_status === 'sharing_first_place' ? '#3b82f6' :
                                      pub.catalog_status === 'competing' ? '#f59e0b' :
                                      '#6b7280',
                                    color: '#fff',
                                    textTransform: 'uppercase'
                                  }}
                                >
                                  {pub.catalog_status === 'winning' ? '🏆 Ganando' :
                                   pub.catalog_status === 'sharing_first_place' ? '🤝 Empatando' :
                                   pub.catalog_status === 'competing' ? '⚠️ Perdiendo' :
                                   pub.catalog_status}
                                </span>
                              ) : pub.catalog_product_id ? (
                                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Catálogo</span>
                              ) : (
                                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Tradicional</span>
                              )}
                            </td>
                            <td style={{ fontSize: '11px' }}>
                              {pub.catalog_product_id && pub.catalog_status === 'winning' && pub.catalog_winner_price && (
                                <span style={{ color: '#22c55e', fontWeight: '600' }}>
                                  Ganando a ${pub.catalog_winner_price.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                                </span>
                              )}
                              {pub.catalog_product_id && pub.catalog_status === 'competing' && pub.catalog_price_to_win && (
                                <span style={{ color: '#f59e0b', fontWeight: '600' }}>
                                  Necesita ${pub.catalog_price_to_win.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                                </span>
                              )}
                              {pub.catalog_product_id && pub.catalog_status === 'sharing_first_place' && pub.catalog_winner_price && (
                                <span style={{ color: '#3b82f6', fontWeight: '600' }}>
                                  Empatando a ${pub.catalog_winner_price.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                                </span>
                              )}
                              {(!pub.catalog_product_id || !pub.catalog_status) && '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* PROVEEDOR */}
              {detalle.proveedor && detalle.proveedor.nombre && (
                <section className="info-section">
                  <h3>🏭 Información de Compra</h3>
                  <div className="info-grid">
                    <div className="info-item">
                      <span className="info-label">Proveedor:</span>
                      <span className="info-value highlight">{detalle.proveedor.nombre}</span>
                    </div>
                    {detalle.proveedor.ultima_compra && (
                      <div className="info-item">
                        <span className="info-label">Última Compra:</span>
                        <span className="info-value">
                          {new Date(detalle.proveedor.ultima_compra).toLocaleDateString('es-AR')}
                        </span>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* VENTAS */}
              {detalle.ventas && (
                <section className="info-section">
                  <h3>📊 Ventas en MercadoLibre</h3>
                  <div className="ventas-grid">
                    <div className="venta-periodo">
                      <div className="periodo-header">Últimos 7 días</div>
                      <div className="periodo-stats">
                        <div className="stat-item">
                          <span className="stat-label">Unidades:</span>
                          <span className="stat-value highlight">
                            {detalle.ventas.ultimos_7_dias.cantidad_vendida}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Ventas:</span>
                          <span className="stat-value">
                            {detalle.ventas.ultimos_7_dias.numero_ventas}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Monto:</span>
                          <span className="stat-value">
                            ${detalle.ventas.ultimos_7_dias.monto_total.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="venta-periodo">
                      <div className="periodo-header">Últimos 15 días</div>
                      <div className="periodo-stats">
                        <div className="stat-item">
                          <span className="stat-label">Unidades:</span>
                          <span className="stat-value highlight">
                            {detalle.ventas.ultimos_15_dias.cantidad_vendida}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Ventas:</span>
                          <span className="stat-value">
                            {detalle.ventas.ultimos_15_dias.numero_ventas}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Monto:</span>
                          <span className="stat-value">
                            ${detalle.ventas.ultimos_15_dias.monto_total.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="venta-periodo">
                      <div className="periodo-header">Últimos 30 días</div>
                      <div className="periodo-stats">
                        <div className="stat-item">
                          <span className="stat-label">Unidades:</span>
                          <span className="stat-value highlight">
                            {detalle.ventas.ultimos_30_dias.cantidad_vendida}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Ventas:</span>
                          <span className="stat-value">
                            {detalle.ventas.ultimos_30_dias.numero_ventas}
                          </span>
                        </div>
                        <div className="stat-item">
                          <span className="stat-label">Monto:</span>
                          <span className="stat-value">
                            ${detalle.ventas.ultimos_30_dias.monto_total.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </section>
              )}

              {/* AUDITORÍA */}
              {detalle.pricing.usuario_modifico && (
                <section className="info-section">
                  <h3>📝 Última Modificación</h3>
                  <div className="info-grid">
                    <div className="info-item">
                      <span className="info-label">Usuario:</span>
                      <span className="info-value">{detalle.pricing.usuario_modifico}</span>
                    </div>
                    <div className="info-item">
                      <span className="info-label">Fecha:</span>
                      <span className="info-value">
                        {new Date(detalle.pricing.fecha_modificacion).toLocaleString('es-AR')}
                      </span>
                    </div>
                  </div>
                </section>
              )}
            </>
          ) : (
            <p>No se pudo cargar la información</p>
          )}
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-primary">Cerrar</button>
        </div>
      </div>
    </div>
  );
};

export default ModalInfoProducto;
