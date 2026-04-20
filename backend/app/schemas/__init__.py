"""Schemas Pydantic v2 por dominio.

Módulo agregador. Cada archivo vive independiente y se importa bajo
demanda desde los routers / servicios. Centralizar aquí genera ciclos
circulares al escalar — NO hacer `from app.schemas.* import *`.
"""
