"""
Servicio de Alertas
Lógica de negocio para el sistema de alertas globales.
"""

from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.alerta import Alerta, AlertaUsuarioDestinatario, AlertaUsuarioEstado, ConfiguracionAlerta
from app.models.usuario import Usuario


class AlertasService:
    """Servicio para gestión de alertas"""

    def __init__(self, db: Session):
        self.db = db

    def obtener_alertas_activas_para_usuario(self, usuario: Usuario, limit: int = 50, offset: int = 0) -> List[Alerta]:
        """
        Obtiene las alertas activas que debe ver un usuario con paginación.

        Filtros aplicados:
        1. Alerta está activa
        2. Fecha vigente (fecha_desde <= now <= fecha_hasta o fecha_hasta is null)
        3. Usuario está en roles_destinatarios O en usuarios_destinatarios
        4. Usuario NO cerró la alerta (excepto si es persistent=True)

        Retorna alertas ordenadas por prioridad DESC (mayor prioridad primero).
        """
        now = datetime.now(timezone.utc)

        # Subquery: IDs de alertas que el usuario cerró
        from sqlalchemy import select

        alertas_cerradas_ids = (
            select(AlertaUsuarioEstado.alerta_id)
            .where(AlertaUsuarioEstado.usuario_id == usuario.id, AlertaUsuarioEstado.cerrada == True)
            .scalar_subquery()
        )

        # Query principal
        query = self.db.query(Alerta).filter(
            # Alerta activa
            Alerta.activo == True,
            # Vigente
            Alerta.fecha_desde <= now,
            or_(Alerta.fecha_hasta.is_(None), Alerta.fecha_hasta >= now),
        )

        # Filtro: destinatarios (roles O usuarios específicos)
        # Usar operador JSONB nativo de PostgreSQL (@>)
        query = query.filter(
            or_(
                # Todos los usuarios: roles_destinatarios @> '["*"]'
                Alerta.roles_destinatarios.contains(["*"]),
                # Rol del usuario está en la lista
                Alerta.roles_destinatarios.contains([usuario.rol_codigo]),
                # Usuario específico en la lista
                Alerta.id.in_(
                    self.db.query(AlertaUsuarioDestinatario.alerta_id).filter(
                        AlertaUsuarioDestinatario.usuario_id == usuario.id
                    )
                ),
            )
        )

        # Filtro: NO cerradas (excepto persistent)
        query = query.filter(
            or_(
                # Alerta persistente (siempre se muestra)
                Alerta.persistent == True,
                # No fue cerrada por el usuario
                ~Alerta.id.in_(alertas_cerradas_ids),
            )
        )

        # Ordenar por prioridad DESC y aplicar paginación
        alertas = query.order_by(Alerta.prioridad.desc(), Alerta.created_at.desc()).limit(limit).offset(offset).all()

        return alertas

    def marcar_alerta_cerrada(self, alerta_id: int, usuario_id: int) -> bool:
        """
        Marca una alerta como cerrada para un usuario específico.
        Crea o actualiza el registro en alertas_usuarios_estado.

        Returns:
            True si se marcó exitosamente
        """
        estado = (
            self.db.query(AlertaUsuarioEstado)
            .filter(AlertaUsuarioEstado.alerta_id == alerta_id, AlertaUsuarioEstado.usuario_id == usuario_id)
            .first()
        )

        if estado:
            # Ya existe, actualizar
            estado.cerrada = True
            estado.fecha_cerrada = datetime.now(timezone.utc)
            # updated_at se maneja automáticamente con onupdate
        else:
            # Crear nuevo
            estado = AlertaUsuarioEstado(
                alerta_id=alerta_id, usuario_id=usuario_id, cerrada=True, fecha_cerrada=datetime.now(timezone.utc)
            )
            self.db.add(estado)

        self.db.commit()
        return True

    def obtener_configuracion(self) -> ConfiguracionAlerta:
        """
        Obtiene la configuración global de alertas.
        Si no existe, crea una con valores por defecto.
        """
        config = self.db.query(ConfiguracionAlerta).filter(ConfiguracionAlerta.id == 1).first()

        if not config:
            config = ConfiguracionAlerta(id=1, max_alertas_visibles=1)
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)

        return config

    def actualizar_configuracion(self, max_alertas_visibles: int, updated_by_id: int) -> ConfiguracionAlerta:
        """
        Actualiza la configuración global de alertas.
        """
        config = self.obtener_configuracion()
        config.max_alertas_visibles = max_alertas_visibles
        config.updated_by_id = updated_by_id
        # updated_at se maneja automáticamente con onupdate

        self.db.commit()
        self.db.refresh(config)

        return config

    def crear_alerta(
        self,
        titulo: str,
        mensaje: str,
        variant: str,
        roles_destinatarios: List[str],
        usuarios_destinatarios_ids: Optional[List[int]] = None,
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
        dismissible: bool = True,
        persistent: bool = False,
        activo: bool = False,
        fecha_desde: datetime = None,
        fecha_hasta: Optional[datetime] = None,
        prioridad: int = 0,
        duracion_segundos: int = 5,
        created_by_id: Optional[int] = None,
    ) -> Alerta:
        """Crea una nueva alerta"""
        if fecha_desde is None:
            fecha_desde = datetime.now(timezone.utc)

        alerta = Alerta(
            titulo=titulo,
            mensaje=mensaje,
            variant=variant,
            roles_destinatarios=roles_destinatarios,
            action_label=action_label,
            action_url=action_url,
            dismissible=dismissible,
            persistent=persistent,
            activo=activo,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            prioridad=prioridad,
            duracion_segundos=duracion_segundos,
            created_by_id=created_by_id,
        )

        self.db.add(alerta)
        self.db.flush()  # Para obtener el ID

        # Agregar usuarios destinatarios si se especificaron
        if usuarios_destinatarios_ids:
            for usuario_id in usuarios_destinatarios_ids:
                dest = AlertaUsuarioDestinatario(alerta_id=alerta.id, usuario_id=usuario_id)
                self.db.add(dest)

        self.db.commit()
        self.db.refresh(alerta)

        return alerta

    def actualizar_alerta(
        self,
        alerta_id: int,
        titulo: Optional[str] = None,
        mensaje: Optional[str] = None,
        variant: Optional[str] = None,
        roles_destinatarios: Optional[List[str]] = None,
        usuarios_destinatarios_ids: Optional[List[int]] = None,
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
        dismissible: Optional[bool] = None,
        persistent: Optional[bool] = None,
        activo: Optional[bool] = None,
        fecha_desde: Optional[datetime] = None,
        fecha_hasta: Optional[datetime] = None,
        prioridad: Optional[int] = None,
        duracion_segundos: Optional[int] = None,
    ) -> Optional[Alerta]:
        """Actualiza una alerta existente"""
        alerta = self.db.query(Alerta).filter(Alerta.id == alerta_id).first()

        if not alerta:
            return None

        if titulo is not None:
            alerta.titulo = titulo
        if mensaje is not None:
            alerta.mensaje = mensaje
        if variant is not None:
            alerta.variant = variant
        if roles_destinatarios is not None:
            alerta.roles_destinatarios = roles_destinatarios
        if action_label is not None:
            alerta.action_label = action_label
        if action_url is not None:
            alerta.action_url = action_url
        if dismissible is not None:
            alerta.dismissible = dismissible
        if persistent is not None:
            alerta.persistent = persistent
        if activo is not None:
            alerta.activo = activo
        if fecha_desde is not None:
            alerta.fecha_desde = fecha_desde
        if fecha_hasta is not None:
            alerta.fecha_hasta = fecha_hasta
        if prioridad is not None:
            alerta.prioridad = prioridad
        if duracion_segundos is not None:
            alerta.duracion_segundos = duracion_segundos

        # Actualizar usuarios destinatarios si se especificaron
        if usuarios_destinatarios_ids is not None:
            # Eliminar existentes
            self.db.query(AlertaUsuarioDestinatario).filter(AlertaUsuarioDestinatario.alerta_id == alerta_id).delete()

            # Agregar nuevos
            for usuario_id in usuarios_destinatarios_ids:
                dest = AlertaUsuarioDestinatario(alerta_id=alerta.id, usuario_id=usuario_id)
                self.db.add(dest)

        # updated_at se maneja automáticamente con onupdate

        self.db.commit()
        self.db.refresh(alerta)

        return alerta

    def eliminar_alerta(self, alerta_id: int) -> bool:
        """Elimina una alerta (soft delete: marcar como inactiva)"""
        alerta = self.db.query(Alerta).filter(Alerta.id == alerta_id).first()

        if not alerta:
            return False

        # Soft delete
        alerta.activo = False
        self.db.commit()

        return True

    def obtener_alerta(self, alerta_id: int) -> Optional[Alerta]:
        """Obtiene una alerta por ID"""
        return self.db.query(Alerta).filter(Alerta.id == alerta_id).first()

    def listar_alertas(self, activo: Optional[bool] = None, limit: int = 100, offset: int = 0) -> List[Alerta]:
        """Lista todas las alertas con filtros opcionales"""
        query = self.db.query(Alerta)

        if activo is not None:
            query = query.filter(Alerta.activo == activo)

        query = query.order_by(Alerta.prioridad.desc(), Alerta.created_at.desc())

        return query.limit(limit).offset(offset).all()
