"""
Servicio para generar zonas de reparto usando K-Means clustering.

Algoritmo:
1. Obtener envíos Turbo pendientes (sin asignar)
2. Filtrar solo los geocodificados (lat/lng válidos)
3. Aplicar K-Means para agrupar en K clusters (K = cantidad_motoqueros)
4. Generar polígono ConvexHull por cada cluster
5. Retornar zonas con nombre, color, cantidad de envíos

Ventajas:
- Balancea automáticamente la cantidad de paquetes por motoquero
- Se adapta a la distribución REAL de envíos del día
- No requiere APIs externas
"""

import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sklearn.cluster import KMeans
from shapely.geometry import Polygon, MultiPoint
from shapely.errors import GeometryTypeError

logger = logging.getLogger(__name__)

# Colores para zonas (máximo 6 motoqueros)
COLORES_ZONAS = [
    "#ef4444",  # Rojo - Zona 1
    "#3b82f6",  # Azul - Zona 2
    "#f59e0b",  # Naranja - Zona 3
    "#8b5cf6",  # Violeta - Zona 4
    "#10b981",  # Verde - Zona 5
    "#ec4899",  # Rosa - Zona 6
]


def generar_zonas_kmeans(envios_coords: List[Tuple[float, float, int]], cantidad_zonas: int) -> List[Dict[str, Any]]:
    """
    Genera zonas usando K-Means clustering sobre envíos geocodificados.

    Args:
        envios_coords: Lista de tuplas (lat, lng, envio_id)
        cantidad_zonas: Cantidad de clusters/zonas a crear (K)

    Returns:
        Lista de diccionarios con información de cada zona:
        [
            {
                'nombre': 'Zona 1 Norte',
                'poligono': {...},  # GeoJSON Polygon
                'color': '#ef4444',
                'cantidad_envios': 15,
                'descripcion': 'Zona generada automáticamente (15 envíos)',
                'envios_ids': [123, 456, ...]
            },
            ...
        ]
    """
    if not envios_coords:
        logger.warning("No hay envíos geocodificados para clustering")
        return []

    if len(envios_coords) < cantidad_zonas:
        logger.warning(
            f"Solo hay {len(envios_coords)} envíos geocodificados, menos que {cantidad_zonas} zonas solicitadas"
        )
        # Ajustar cantidad de zonas a cantidad de envíos
        cantidad_zonas = len(envios_coords)

    try:
        # Preparar datos para K-Means
        coords = np.array([(lat, lng) for lat, lng, _ in envios_coords])
        envios_ids = [envio_id for _, _, envio_id in envios_coords]

        logger.info(f"Aplicando K-Means con K={cantidad_zonas} sobre {len(coords)} envíos")

        # Aplicar K-Means con múltiples inicializaciones para mejor distribución
        kmeans = KMeans(
            n_clusters=cantidad_zonas,
            init="k-means++",  # Mejor inicialización que random
            n_init=50,  # Más inicializaciones = mejor resultado (default es 10)
            max_iter=300,
            random_state=None,  # Permitir aleatoriedad para mejor distribución
        )
        labels = kmeans.fit_predict(coords)

        # Generar zonas por cluster
        zonas = []
        for cluster_id in range(cantidad_zonas):
            # Filtrar puntos del cluster
            mask = labels == cluster_id
            cluster_coords = coords[mask]
            cluster_envios = [envios_ids[i] for i, is_in_cluster in enumerate(mask) if is_in_cluster]

            if len(cluster_coords) == 0:
                logger.warning(f"Cluster {cluster_id} vacío, saltando")
                continue

            # Generar polígono ConvexHull
            poligono_geojson = generar_convex_hull(cluster_coords)

            if not poligono_geojson:
                logger.warning(f"No se pudo generar polígono para cluster {cluster_id}")
                continue

            # Determinar orientación geográfica del cluster
            orientacion = calcular_orientacion(cluster_coords)

            zona = {
                "nombre": f"Zona {cluster_id + 1} {orientacion}",
                "poligono": poligono_geojson,
                "color": COLORES_ZONAS[cluster_id % len(COLORES_ZONAS)],
                "cantidad_envios": len(cluster_envios),
                "descripcion": f"Zona generada automáticamente ({len(cluster_envios)} envíos - {orientacion})",
                "envios_ids": cluster_envios,
            }

            zonas.append(zona)
            logger.info(
                f"Zona {cluster_id + 1} ({orientacion}): "
                f"{len(cluster_envios)} envíos, "
                f"{len(poligono_geojson['coordinates'][0])} puntos en polígono"
            )

        return zonas

    except Exception as e:
        logger.error(f"Error en K-Means clustering: {e}", exc_info=True)
        return []


def generar_convex_hull(coords: np.ndarray) -> Optional[Dict[str, Any]]:
    """
    Genera un polígono ConvexHull (envolvente convexa) desde coordenadas.

    El ConvexHull es el polígono más pequeño que contiene todos los puntos.
    Similar a poner una banda elástica alrededor de los puntos.

    Args:
        coords: Array numpy de shape (N, 2) con (lat, lng)

    Returns:
        GeoJSON Polygon o None si falla
    """
    try:
        if len(coords) < 3:
            # ConvexHull requiere al menos 3 puntos
            # Si hay 1-2 puntos, crear buffer circular
            logger.warning(f"Solo {len(coords)} puntos, creando buffer")
            return generar_buffer_circular(coords)

        # Invertir coords a (lng, lat) para GeoJSON
        points = [(lng, lat) for lat, lng in coords]

        # Crear MultiPoint y obtener ConvexHull
        multipoint = MultiPoint(points)
        hull = multipoint.convex_hull

        # Convertir a GeoJSON
        if isinstance(hull, Polygon):
            # Extraer coordenadas exteriores
            exterior_coords = list(hull.exterior.coords)

            return {"type": "Polygon", "coordinates": [exterior_coords]}
        else:
            logger.warning(f"ConvexHull no es Polygon: {type(hull)}")
            return None

    except (GeometryTypeError, Exception) as e:
        logger.error(f"Error generando ConvexHull: {e}")
        return None


def generar_buffer_circular(coords: np.ndarray, radio_km: float = 1.0) -> Dict[str, Any]:
    """
    Genera un polígono circular alrededor de 1-2 puntos.

    Args:
        coords: Array numpy de coordenadas
        radio_km: Radio del círculo en kilómetros

    Returns:
        GeoJSON Polygon
    """
    # Centroide
    centroid_lat = coords[:, 0].mean()
    centroid_lng = coords[:, 1].mean()

    # Aproximación: 1 grado lat/lng ≈ 111 km
    radio_grados = radio_km / 111.0

    # Generar círculo con 20 puntos
    num_puntos = 20
    angulos = np.linspace(0, 2 * np.pi, num_puntos)

    circulo_coords = [
        (centroid_lng + radio_grados * np.cos(angulo), centroid_lat + radio_grados * np.sin(angulo))
        for angulo in angulos
    ]

    # Cerrar polígono (primer punto = último punto)
    circulo_coords.append(circulo_coords[0])

    return {"type": "Polygon", "coordinates": [circulo_coords]}


def calcular_orientacion(coords: np.ndarray) -> str:
    """
    Calcula la orientación geográfica promedio de un cluster.

    Args:
        coords: Array numpy de coordenadas (lat, lng)

    Returns:
        String con orientación: 'Norte', 'Sur', 'Este', 'Oeste', 'Centro', etc.
    """
    # Felipe Vallese 1559, CABA (centro de distribución)
    CENTRO_LAT = -34.6282
    CENTRO_LNG = -58.4642

    # Calcular centroide del cluster
    centroid_lat = coords[:, 0].mean()
    centroid_lng = coords[:, 1].mean()

    # Calcular diferencia respecto al centro
    delta_lat = centroid_lat - CENTRO_LAT
    delta_lng = centroid_lng - CENTRO_LNG

    # Umbrales (en grados, ~0.01 grados ≈ 1 km)
    UMBRAL_CENTRO = 0.02

    if abs(delta_lat) < UMBRAL_CENTRO and abs(delta_lng) < UMBRAL_CENTRO:
        return "Centro"

    # Determinar orientación cardinal
    if abs(delta_lat) > abs(delta_lng):
        # Predomina Norte/Sur
        return "Norte" if delta_lat > 0 else "Sur"
    else:
        # Predomina Este/Oeste
        return "Oeste" if delta_lng < 0 else "Este"


def validar_envios_geocodificados(
    total_envios: int, envios_geocodificados: int, porcentaje_minimo: float = 0.7
) -> Tuple[bool, str]:
    """
    Valida que haya suficientes envíos geocodificados para clustering.

    Args:
        total_envios: Cantidad total de envíos Turbo pendientes
        envios_geocodificados: Cantidad de envíos con lat/lng válidos
        porcentaje_minimo: Porcentaje mínimo requerido (0.7 = 70%)

    Returns:
        Tupla (es_valido, mensaje)
    """
    if total_envios == 0:
        return False, "No hay envíos Turbo pendientes"

    porcentaje_actual = envios_geocodificados / total_envios

    if porcentaje_actual < porcentaje_minimo:
        return False, (
            f"Solo {envios_geocodificados}/{total_envios} envíos geocodificados "
            f"({porcentaje_actual:.0%}). Se requiere al menos {porcentaje_minimo:.0%}. "
            f"Ejecutá geocoding batch primero."
        )

    return True, f"✅ {envios_geocodificados}/{total_envios} envíos geocodificados ({porcentaje_actual:.0%})"
