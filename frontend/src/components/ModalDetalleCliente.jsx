import { useState, useEffect } from 'react';
import {
  X,
  Edit3,
  Save,
  XCircle,
  ClipboardList,
  Phone,
  MapPin,
  Briefcase,
  ShoppingCart,
  Clock,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import styles from './ModalDetalleCliente.module.css';
import api from '../services/api';

export default function ModalDetalleCliente({ cliente, onClose, onActualizar }) {
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null); // { tipo: 'success'|'error', texto: '...' }
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
    setMensaje(null);
    try {
      const response = await api.patch(
        `/clientes/${cliente.cust_id}?comp_id=${cliente.comp_id}`,
        datosEdit
      );

      setEditando(false);
      onActualizar(response.data);
      setMensaje({ tipo: 'success', texto: 'Cliente actualizado correctamente' });
    } catch {
      setMensaje({ tipo: 'error', texto: 'Error al actualizar cliente' });
    } finally {
      setGuardando(false);
    }
  };

  const handleCancelar = () => {
    setEditando(false);
    setMensaje(null);
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

  const updateField = (field, value) => {
    setDatosEdit(prev => ({ ...prev, [field]: value }));
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
          <h2>Cliente #{cliente.cust_id}</h2>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Cerrar modal">
            <X size={18} />
          </button>
        </div>

        <div className={styles.body}>
          {/* Feedback message */}
          {mensaje && (
            <div className={mensaje.tipo === 'success' ? styles.msgSuccess : styles.msgError}>
              {mensaje.tipo === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
              {mensaje.texto}
              <button onClick={() => setMensaje(null)} aria-label="Cerrar mensaje">
                <X size={14} />
              </button>
            </div>
          )}

          {/* Datos Principales */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3><ClipboardList size={16} /> Datos Principales</h3>
              {!editando ? (
                <button
                  className={styles.btnEdit}
                  onClick={() => setEditando(true)}
                >
                  <Edit3 size={14} />
                  Editar
                </button>
              ) : (
                <div className={styles.editActions}>
                  <button
                    className={styles.btnSave}
                    onClick={handleGuardar}
                    disabled={guardando}
                  >
                    <Save size={14} />
                    {guardando ? 'Guardando...' : 'Guardar'}
                  </button>
                  <button
                    className={styles.btnCancel}
                    onClick={handleCancelar}
                    disabled={guardando}
                  >
                    <XCircle size={14} />
                    Cancelar
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
                    onChange={(e) => updateField('cust_name', e.target.value)}
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
                    onChange={(e) => updateField('cust_email', e.target.value)}
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

          {/* Contacto */}
          <div className={styles.section}>
            <h3><Phone size={16} /> Contacto</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Teléfono</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_phone1}
                    onChange={(e) => updateField('cust_phone1', e.target.value)}
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
                    onChange={(e) => updateField('cust_cellphone', e.target.value)}
                    className={styles.input}
                  />
                ) : (
                  <span className={styles.value}>{cliente.cust_cellphone || '-'}</span>
                )}
              </div>
            </div>
          </div>

          {/* Dirección */}
          <div className={styles.section}>
            <h3><MapPin size={16} /> Dirección</h3>
            <div className={styles.grid}>
              <div className={styles.field}>
                <label>Dirección</label>
                {editando ? (
                  <input
                    type="text"
                    value={datosEdit.cust_address}
                    onChange={(e) => updateField('cust_address', e.target.value)}
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
                    onChange={(e) => updateField('cust_city', e.target.value)}
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
                    onChange={(e) => updateField('cust_zip', e.target.value)}
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

          {/* Información Fiscal */}
          <div className={styles.section}>
            <h3><Briefcase size={16} /> Información Fiscal y Comercial</h3>
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

          {/* MercadoLibre */}
          {cliente.cust_mercadolibreid && (
            <div className={styles.section}>
              <h3><ShoppingCart size={16} /> MercadoLibre</h3>
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

          {/* Auditoría */}
          <div className={styles.section}>
            <h3><Clock size={16} /> Auditoría</h3>
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
