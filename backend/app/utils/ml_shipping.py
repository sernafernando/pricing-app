"""Utilidades compartidas para parsing de shipping de MercadoLibre."""

import json


def parse_shipping_tags(raw_tags: object) -> tuple[list, bool]:
    """Parsea shipping_tags y detecta mandatory_free_shipping.

    Args:
        raw_tags: Tags crudos (str JSON, list, o None)

    Returns:
        Tupla (tags_list, is_mandatory_free_shipping)
    """
    tags: list = []
    if raw_tags is not None:
        if isinstance(raw_tags, str):
            try:
                tags = json.loads(raw_tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        elif isinstance(raw_tags, list):
            tags = raw_tags
    mandatory = "mandatory_free_shipping" in tags
    return tags, mandatory
