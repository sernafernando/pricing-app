from app.models.publicacion_ml import PublicacionML
from app.models.producto import ProductoERP, ProductoPricing, HistorialPrecio
from app.models.usuario import Usuario
from app.models.tipo_cambio import TipoCambio
from app.models.subcategoria import Subcategoria
from app.models.comision_config import GrupoComision, SubcategoriaGrupo, ComisionListaGrupo
from app.models.auditoria_precio import AuditoriaPrecio
from app.models.precio_ml import PrecioML
from app.models.auditoria import Auditoria
from app.models.marca_pm import MarcaPM
from app.models.mla_banlist import MLABanlist
from app.models.item_sin_mla_banlist import ItemSinMLABanlist
from app.models.comparacion_listas_banlist import ComparacionListasBanlist
from app.models.calculo_pricing import CalculoPricing
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_publication_snapshot import MLPublicationSnapshot
from app.models.tb_item_serials import TbItemSerial
from app.models.tb_item_transaction_serials import TbItemTransactionSerial
from app.models.notificacion import Notificacion
from app.models.tb_customer import TBCustomer
from app.models.tb_branch import TBBranch
from app.models.tb_salesman import TBSalesman
from app.models.tb_document_file import TBDocumentFile
from app.models.tb_fiscal_class import TBFiscalClass
from app.models.tb_tax_number_type import TBTaxNumberType
from app.models.tb_state import TBState
from app.models.tb_item_association import TbItemAssociation
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.markup_tienda import MarkupTiendaBrand
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.pedido_preparacion_cache import PedidoPreparacionCache
from app.models.export_87_snapshot import Export87Snapshot
from app.models.produccion_banlist import ProduccionBanlist, ProduccionPrearmado
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.alerta import Alerta, AlertaUsuarioDestinatario, AlertaUsuarioEstado, ConfiguracionAlerta
from app.models.asignacion import Asignacion
from app.models.cuenta_corriente_proveedor import CuentaCorrienteProveedor
from app.models.cuenta_corriente_cliente import CuentaCorrienteCliente
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_envio_audit import EtiquetaEnvioAudit
from app.models.operador import Operador
from app.models.operador_config_tab import OperadorConfigTab
from app.models.operador_actividad import OperadorActividad
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.models.mercadolibre_user_data import MercadoLibreUserData
from app.models.tb_sale_order_serial import TbSaleOrderSerial
from app.models.tb_storage import TbStorage
from app.models.tb_rma_detail import TbRMADetail
from app.models.tb_rma_header import TbRMAHeader
from app.models.tb_rma_add_items import TbRMAAddItems
from app.models.tb_rma_detail_attrib_history import TbRMADetailAttribHistory
from app.models.tb_rma_supplier_cn_pending import TbRMASupplierCNPending
from app.models.rma_seguimiento_opcion import RmaSeguimientoOpcion
from app.models.rma_caso import RmaCaso
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_claim_ml import RmaClaimML
from app.models.rma_claim_ml_message import RmaClaimMLMessage
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.weather_history import WeatherHistory

# RRHH — Recursos Humanos
from app.models.empresa import Empresa
from app.models.rrhh_empleado import RRHHEmpleado, EstadoEmpleado
from app.models.rrhh_schema_legajo import RRHHSchemaLegajo
from app.models.rrhh_tipo_documento import RRHHTipoDocumento
from app.models.rrhh_documento import RRHHDocumento
from app.models.rrhh_legajo_historial import RRHHLegajoHistorial
from app.models.rrhh_presentismo import RRHHPresentismoDiario, EstadoPresentismo
from app.models.rrhh_art_caso import RRHHArtCaso, EstadoArt
from app.models.rrhh_art_documento import RRHHArtDocumento
from app.models.rrhh_sancion import RRHHTipoSancion, RRHHSancion
from app.models.rrhh_vacaciones import (
    RRHHVacacionesPeriodo,
    RRHHVacacionesSolicitud,
    EstadoSolicitudVacaciones,
)
from app.models.rrhh_herramienta import RRHHAsignacionHerramienta
from app.models.rrhh_cuenta_corriente import (
    RRHHCuentaCorriente,
    RRHHCuentaCorrienteMovimiento,
    TipoMovimientoCC,
)
from app.models.rrhh_fichada import RRHHFichada, OrigenFichada, TipoFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_hikvision_user import RRHHHikvisionUser
from app.models.rrhh_motivo_ausencia import RRHHMotivoAusencia
from app.models.rrhh_motivo_baja import RRHHMotivoBaja

# Documentos — Templates PDF
from app.models.document_template import DocumentTemplate

# Proveedores — Módulo Administración
from app.models.rma_proveedor import RmaProveedor  # must be before Proveedor (relationship target)
from app.models.proveedor_direccion import ProveedorDireccion
from app.models.proveedor_banco import ProveedorBanco
from app.models.proveedor_contacto import ProveedorContacto
from app.models.proveedor import Proveedor, OrigenProveedor
from app.models.proveedor_datos_fiscales import ProveedorDatosFiscales

# Bancos — Módulo Administración
from app.models.banco_empresa import BancoEmpresa

# Impuestos — Módulo Administración
from app.models.impuesto_empresa import ImpuestoEmpresa

# Caja — Módulo Administración
from app.models.caja import (
    Caja,
    CajaMovimiento,
    CajaCategoria,
    CajaTipoDocumento,
    CajaDocumento,
    CajaDocumentoMovimiento,
    CajaArchivo,
    CajaTag,
    CajaMovimientoTag,
)

# Compras — Módulo Administración (v1)
from app.models.numeracion_contador import NumeracionContador
from app.models.tb_sale_document import SaleDocument
from app.models.pedido_compra import PedidoCompra
from app.models.compra_evento import CompraEvento
from app.models.orden_pago import OrdenPago
from app.models.imputacion import Imputacion
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.cc_reconciliacion_log import CCReconciliacionLog
from app.models.compras_papelera import ComprasPapelera

__all__ = [
    "ProductoERP",
    "ProductoPricing",
    "HistorialPrecio",
    "Usuario",
    "TipoCambio",
    "Subcategoria",
    "GrupoComision",
    "SubcategoriaGrupo",
    "ComisionListaGrupo",
    "PublicacionML",
    "AuditoriaPrecio",
    "PrecioML",
    "Auditoria",
    "MarcaPM",
    "MLABanlist",
    "ItemSinMLABanlist",
    "ComparacionListasBanlist",
    "CalculoPricing",
    "MercadoLibreItemPublicado",
    "MLPublicationSnapshot",
    "TbItemSerial",
    "TbItemTransactionSerial",
    "Notificacion",
    "TBCustomer",
    "TBBranch",
    "TBSalesman",
    "TBDocumentFile",
    "TBFiscalClass",
    "TBTaxNumberType",
    "TBState",
    "TbItemAssociation",
    "OffsetGanancia",
    "OffsetGrupo",
    "OffsetGrupoFiltro",
    "OffsetGrupoConsumo",
    "OffsetGrupoResumen",
    "OffsetIndividualConsumo",
    "OffsetIndividualResumen",
    "MarkupTiendaBrand",
    "Permiso",
    "RolPermisoBase",
    "UsuarioPermisoOverride",
    "Rol",
    "PedidoPreparacionCache",
    "Export87Snapshot",
    "ProduccionBanlist",
    "ProduccionPrearmado",
    "Motoquero",
    "ZonaReparto",
    "AsignacionTurbo",
    "GeocodingCache",
    "Alerta",
    "AlertaUsuarioDestinatario",
    "AlertaUsuarioEstado",
    "ConfiguracionAlerta",
    "Asignacion",
    "CuentaCorrienteProveedor",
    "CuentaCorrienteCliente",
    "CodigoPostalCordon",
    "Logistica",
    "Transporte",
    "EtiquetaEnvio",
    "EtiquetaEnvioAudit",
    "Operador",
    "OperadorConfigTab",
    "OperadorActividad",
    "LogisticaCostoCordon",
    "MercadoLibreUserData",
    "TbSaleOrderSerial",
    "TbStorage",
    "TbRMADetail",
    "TbRMAHeader",
    "TbRMAAddItems",
    "TbRMADetailAttribHistory",
    "TbRMASupplierCNPending",
    "RmaSeguimientoOpcion",
    "RmaCaso",
    "RmaCasoItem",
    "RmaCasoHistorial",
    "RmaClaimML",
    "RmaClaimMLMessage",
    "EtiquetaColecta",
    "WeatherHistory",
    # RRHH
    "RRHHEmpleado",
    "EstadoEmpleado",
    "RRHHSchemaLegajo",
    "RRHHTipoDocumento",
    "RRHHDocumento",
    "RRHHLegajoHistorial",
    # RRHH — Presentismo + ART
    "RRHHPresentismoDiario",
    "EstadoPresentismo",
    "RRHHArtCaso",
    "EstadoArt",
    "Empresa",
    "RRHHArtDocumento",
    # RRHH — Sanciones
    "RRHHTipoSancion",
    "RRHHSancion",
    # RRHH — Vacaciones
    "RRHHVacacionesPeriodo",
    "RRHHVacacionesSolicitud",
    "EstadoSolicitudVacaciones",
    # RRHH — Cuenta Corriente + Herramientas
    "RRHHAsignacionHerramienta",
    "RRHHCuentaCorriente",
    "RRHHCuentaCorrienteMovimiento",
    "TipoMovimientoCC",
    # RRHH — Horarios + Fichadas
    "RRHHFichada",
    "OrigenFichada",
    "TipoFichada",
    "RRHHHorarioConfig",
    "RRHHHorarioExcepcion",
    "RRHHEmpleadoHorario",
    "RRHHHikvisionUser",
    "RRHHMotivoAusencia",
    "RRHHMotivoBaja",
    # Documentos
    "DocumentTemplate",
    # Proveedores — Módulo Administración
    "RmaProveedor",
    "ProveedorDireccion",
    "ProveedorBanco",
    "ProveedorContacto",
    "Proveedor",
    "OrigenProveedor",
    "ProveedorDatosFiscales",
    # Bancos — Módulo Administración
    "BancoEmpresa",
    # Impuestos — Módulo Administración
    "ImpuestoEmpresa",
    # Caja — Módulo Administración
    "Caja",
    "CajaMovimiento",
    "CajaCategoria",
    "CajaTipoDocumento",
    "CajaDocumento",
    "CajaDocumentoMovimiento",
    "CajaArchivo",
    "CajaTag",
    "CajaMovimientoTag",
    # Compras — Módulo Administración (v1)
    "NumeracionContador",
    "SaleDocument",
    "PedidoCompra",
    "CompraEvento",
    "OrdenPago",
    "Imputacion",
    "CCProveedorMovimiento",
    "CCReconciliacionLog",
    "ComprasPapelera",
]
