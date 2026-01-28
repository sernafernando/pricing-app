import { useState, useEffect } from 'react';
import styles from './ModalDetalleCliente.module.css';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL;

export default function ModalDetalleCliente({ cliente, onClose, onActualizar }) {
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [datosEdit, setDatosEdit] = useState({
    cust_name: '',
    cust_email: '',
    cust_phone1: '',
    cust_cellphone: '',
    cust_address: '',
    cust_city: '',
    cust_zip: ''
  });

  useEffect(() => {
    if (cliente) {
      setDatosEdit({
        cust_name: cliente.cust_name || '',
        cust_email: cliente.cust_email || '',
        cust_phone1: cliente.cust_phone1 || '',
        cust_cellphone: cliente.cust_cellphone || '',
        cust_address: cliente.cust_address || '',
        cust_city: cliente.cust_city || '',
        cust_zip: cliente.cust_zip || ''
      });
    }
  }, [cliente]);

  const handleGuardar = async () => {
    setGuardando(true);
    try {
      const response = await axios.patch(
        `${API_URL}/clientes/${cliente.cust_id}?comp_id=${cliente.comp_id}`,
        datosEdit
      );
      
      setEditando(false);
      onActualizar(response.data);
      alert('Cliente actualizado correctamente');
    } catch (error) {
      console.error('Error actualizando cliente:', error);
      alert('Error al actualizar cliente');
    } finally {
      setGuardando(false);
    }
  };

  const handleCancelar = () => {
    setEditando(false);
    // Restaurar datos originales
    setDatosEdit({
      cust_name: cliente.cust_name || '',
      cust_email: cliente.cust_email || '',
      cust_phone1: cliente.cust_phone1 || '',
      cust_cellphone: cliente.cust_cellphone || '',
      cust_address: cliente.cust_address || '',
      cust_city: cliente.cust_city || '',
      cust_zip: cliente.cust_zip || ''
    });
  };

  if (!cliente) return null;

  const formatFecha = (fecha) => {
    if (!fecha) return '-';
    return new Date(fecha).toLocaleDateString('es-AR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>Detalle del Cliente #{cliente.cust_id}</h2>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.body}>
          {/* Sección: Datos Principales */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3>📋 Datos Principales</h3>
              {!editando ? (
                <button 
                  className={styles.btnEdit}
                  onClick={() => setEditando(true)}
                >
                  ✏️ Editar
                </button>
              ) : (
                <div className={styles.editActions}>
                  <button 
                    className={styles.btnSave}
                    onClick={handleGuardar}
                    disabled={guardando}
                  >
                    {guardando ? 'Guardando...' : '💾 Guardar'}
                  </button>
                  <button 
                    className={styles.btnCancel}
                    onClick={handleCancelar}
                    disabled={guardando}
                  >
                    ❌ Cancelar
                  </button>
                </div>
              )}
            </div>

            <div className={styles.grid}>
              <div className={styles.field}>
                <label>ID Cliente</label>
                <span className={styles.value}>{cliente.cust_id}</span>
              </div>

              <div className={styles.field}>
                <label>Nombre Comercial</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_name}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_name: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_name || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Razón Social</label>
                <span className={styles.value}>{cliente.cust_name1 || '-'}</span>
              </div>

              <div className={styles.field}>
                <label>CUIT/DNI</label>
                <span className={styles.value}>{cliente.cust_taxnumber || '-'}</span>
              </div>

              <div className={styles.field}>
                <label>Email</label>
                {editando ? (
                  <input
                    type="email"
                    value={datosEdit.cust_email}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_email: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_email || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Estado</label>
                <span className={cliente.cust_inactive ? styles.badgeDanger : styles.badgeSuccess}>
                  {cliente.cust_inactive ? 'Inactivo' : 'Activo'}
                </span>
              </div>
            </div>
          </div>

          {/* Sección: Contacto */}
          <div className={styles.section}>
            <h3>📞 Contacto</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Teléfono</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_phone1}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_phone1: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_phone1 || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Celular</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_cellphone}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_cellphone: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_cellphone || '-'}</span>
                )}
              </div>
            </div>
          </div>

          {/* Sección: Dirección */}
          <div className={styles.section}>
            <h3>📍 Dirección</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Dirección</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_address}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_address: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_address || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Ciudad</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_city}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_city: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_city || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Código Postal</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_zip}
                    onChange={(e) => setDatosEdit({ ...datosEdit, cust_zip: e.target.value })}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_zip || '-'}</span>
                )}
              </div>

              <div className={styles.field}>
                <label>Provincia</label>
                <span className={styles.value}>{cliente.state_desc || '-'}</span>
              </div>
            </div>
          </div>

          {/* Sección: Información Fiscal */}
          <div className={styles.section}>
            <h3>💼 Información Fiscal y Comercial</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Condición Fiscal</label>
                <span className={styles.value}>{cliente.fc_desc || '-'}</span>
              </div>

              <div className={styles.field}>
                <label>Sucursal</label>
                <span className={styles.value}>{cliente.bra_desc || '-'}</span>
              </div>

              <div className={styles.field}>
                <label>Vendedor</label>
                <span className={styles.value}>{cliente.sm_name || '-'}</span>
              </div>
            </div>
          </div>

          {/* Sección: MercadoLibre */}
          {cliente.cust_mercadolibreid && (
            <div className={styles.section}>
              <h3>🛒 MercadoLibre</h3>
              <div className={styles.grid}>
                <div className={styles.field}>
                  <label>ID ML</label>
                  <span className={styles.value}>{cliente.cust_mercadolibreid}</span>
                </div>

                <div className={styles.field}>
                  <label>Usuario ML</label>
                  <span className={styles.value}>{cliente.cust_mercadolibrenickname || '-'}</span>
                </div>
              </div>
            </div>
          )}

          {/* Sección: Auditoría */}
          <div className={styles.section}>
            <h3>🕐 Auditoría</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Fecha de Alta</label>
                <span className={styles.value}>{formatFecha(cliente.cust_cd)}</span>
              </div>

              <div className={styles.field}>
                <label>Última Actualización</label>
                <span className={styles.value}>{formatFecha(cliente.cust_lastupdate)}</span>
              </div>
            </div>
          </div>
        </div>

        <div className={styles.footer}>
          <button className={styles.btnClose} onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
