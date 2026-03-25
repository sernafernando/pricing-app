"""
Modelo ProveedorDatosFiscales — cache de datos AFIP (Padrón A4).

Guarda los datos fiscales/tributarios consultados via AFIP SDK.
Se refresca on-demand cuando el usuario presiona "Consultar AFIP".

Campos derivados (condicion_iva, inscripto_ganancias, etc.) se extraen
del JSON raw para facilitar consultas SQL y display en UI.
El JSON raw completo se guarda por si se necesitan datos adicionales
sin tener que reconsultar la API.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class ProveedorDatosFiscales(Base):
    __tablename__ = "proveedor_datos_fiscales"

    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── Datos derivados (extraídos del JSON para queries rápidas) ─
    # Condición ante IVA: "Responsable Inscripto", "Monotributista", "Exento", etc.
    condicion_iva = Column(String(100), nullable=True)
    # Inscripción en Ganancias (idImpuesto 10 o 11)
    inscripto_ganancias = Column(Boolean, nullable=True)
    # Estado de la clave fiscal: ACTIVO, INACTIVO, LIMITADO
    estado_clave = Column(String(50), nullable=True)
    # Tipo de persona: FISICA, JURIDICA
    tipo_persona = Column(String(20), nullable=True)
    # Forma jurídica: SA, SRL, SAS, etc.
    forma_juridica = Column(String(100), nullable=True)
    # Razón social tal como figura en AFIP (puede diferir del nombre en ERP)
    razon_social_afip = Column(String(500), nullable=True)
    # Actividad principal (la de orden=1, nomenclador más reciente)
    actividad_principal = Column(String(500), nullable=True)
    actividad_principal_id = Column(Integer, nullable=True)

    # ── Domicilio fiscal (de AFIP, no del ERP) ────────────────────
    domicilio_fiscal = Column(String(500), nullable=True)
    domicilio_fiscal_cp = Column(String(20), nullable=True)
    domicilio_fiscal_provincia = Column(String(100), nullable=True)
    domicilio_fiscal_localidad = Column(String(255), nullable=True)

    # ── JSON raw completo del Padrón A4 ──────────────────────────
    # Se guarda TODO lo que devuelve AFIP para consulta detallada
    padron_a4_raw = Column(JSONB, nullable=True)

    # ── Metadata de consulta ─────────────────────────────────────
    # Qué CUIT se consultó (verificación: puede haber cambiado en proveedores)
    cuit_consultado = Column(String(20), nullable=True)
    # Cuándo se consultó por última vez
    ultima_consulta_afip = Column(DateTime(timezone=True), nullable=True)
    # Error de la última consulta (null si fue exitosa)
    ultimo_error_afip = Column(Text, nullable=True)
    # Qué web service se usó (ws_sr_padron_a4, ws_sr_constancia_inscripcion)
    wsid_consultado = Column(String(50), nullable=True)

    # ── Auditoría ─────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=True,
    )

    # ── Relación ──────────────────────────────────────────────────
    proveedor = relationship("Proveedor", back_populates="datos_fiscales")

    def __repr__(self) -> str:
        return (
            f"<ProveedorDatosFiscales(proveedor_id={self.proveedor_id}, "
            f"condicion_iva='{self.condicion_iva}', "
            f"estado_clave='{self.estado_clave}')>"
        )
