"""
Servicio para asignación automática de envíos Turbo a zonas/motoqueros.

Algoritmo:
1. Obtener envíos pendientes con coordenadas (lat/lng)
2. Obtener zonas activas con sus polígonos GeoJSON
3. Para cada envío:
   - Verificar en qué zona está (point-in-polygon)
   - Asignar al motoquero asociado a esa zona
4. Crear registros en asignaciones_turbo
5. Retornar resumen de asignaciones
"""
import logging
from typing import List, Dict, Any, Tuple, Optional
from shapely.geometry import Point, shape

logger = logging.getLogger(__name__)


def punto_en_poligono(lat: float, lng: float, poligono_geojson: Dict[str, Any]) -> bool:
    """
    Verifica si un punto (lat, lng) está dentro de un polígono GeoJSON.
    
    Args:
        lat: Latitud del punto
        lng: Longitud del punto
        poligono_geojson: Polígono en formato GeoJSON
        
    Returns:
        True si el punto está dentro del polígono, False caso contrario
    """
    try:
        # Crear punto (lng, lat) - GeoJSON usa lng,lat
        punto = Point(lng, lat)
        
        # Convertir GeoJSON a Shapely Polygon
        poligono = shape(poligono_geojson)
        
        # BUFFER: Expandir polígono levemente para incluir puntos en el borde
        # 0.001 grados ≈ 111 metros (suficiente para compensar puntos en el borde)
        poligono_buffered = poligono.buffer(0.001)
        
        # Verificar si el punto está dentro (usando polígono expandido)
        resultado = poligono_buffered.contains(punto)
        
        return resultado
        
    except Exception as e:
        logger.error(f"Error verificando punto en poligono: {e}, poligono_type={type(poligono_geojson)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def asignar_envio_a_zona(
    lat: float,
    lng: float,
    zonas: List[Dict[str, Any]]
) -> Optional[int]:
    """
    Encuentra la zona que contiene un punto dado.
    
    Args:
        lat: Latitud del envío
        lng: Longitud del envío
        zonas: Lista de zonas con formato:
            [
                {
                    'id': 1,
                    'nombre': 'Zona Norte',
                    'poligono': {...},  # GeoJSON
                    'motoquero_id': 5
                },
                ...
            ]
            
    Returns:
        ID de la zona que contiene el punto, o None si no está en ninguna
    """
    logger.debug(f"Buscando zona para punto: lat={lat}, lng={lng}")
    logger.debug(f"Total zonas disponibles: {len(zonas)}")
    
    for zona in zonas:
        if 'poligono' not in zona:
            logger.warning(f"Zona {zona.get('id')} sin poligono definido")
            continue
            
        resultado = punto_en_poligono(lat, lng, zona['poligono'])
        logger.debug(f"  Zona '{zona['nombre']}' (ID {zona['id']}): {'MATCH' if resultado else 'NO MATCH'}")
        
        if resultado:
            logger.info(f"Punto ({lat}, {lng}) encontrado en zona {zona['nombre']}")
            return zona['id']
    
    logger.warning(f"Punto ({lat}, {lng}) NO esta en ninguna de las {len(zonas)} zonas")
    return None


def asignar_envios_automaticamente(
    envios_coords: List[Tuple[str, float, float]],
    zonas_motoqueros: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Asigna envíos a zonas usando point-in-polygon.
    
    Args:
        envios_coords: Lista de (mlshippingid, lat, lng)
        zonas_motoqueros: Lista de zonas con motoquero asignado:
            [
                {
                    'id': 1,
                    'nombre': 'Zona Norte',
                    'poligono': {...},
                    'motoquero_id': 5,
                    'motoquero_nombre': 'Juan Pérez'
                },
                ...
            ]
            
    Returns:
        {
            'asignaciones': [
                {
                    'mlshippingid': '123',
                    'zona_id': 1,
                    'zona_nombre': 'Zona Norte',
                    'motoquero_id': 5,
                    'motoquero_nombre': 'Juan Pérez'
                },
                ...
            ],
            'sin_zona': ['456', '789'],  # IDs de envíos sin zona
            'total_asignados': 25,
            'total_sin_zona': 5
        }
    """
    asignaciones = []
    sin_zona = []
    
    for mlshippingid, lat, lng in envios_coords:
        zona_id = asignar_envio_a_zona(lat, lng, zonas_motoqueros)
        
        if zona_id:
            # Encontrar datos de la zona
            zona = next((z for z in zonas_motoqueros if z['id'] == zona_id), None)
            
            if zona and zona.get('motoquero_id'):
                asignaciones.append({
                    'mlshippingid': mlshippingid,
                    'zona_id': zona_id,
                    'zona_nombre': zona['nombre'],
                    'motoquero_id': zona['motoquero_id'],
                    'motoquero_nombre': zona.get('motoquero_nombre', 'Sin nombre')
                })
            else:
                logger.warning(f"Zona {zona_id} sin motoquero asignado")
                sin_zona.append(mlshippingid)
        else:
            sin_zona.append(mlshippingid)
    
    resultado = {
        'asignaciones': asignaciones,
        'sin_zona': sin_zona,
        'total_asignados': len(asignaciones),
        'total_sin_zona': len(sin_zona)
    }
    
    logger.info(
        f"Asignación automática: {resultado['total_asignados']} asignados, "
        f"{resultado['total_sin_zona']} sin zona"
    )
    
    return resultado
