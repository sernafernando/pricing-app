"""Limits of a publication's data as an operator edits it: the product's copy (Publicaciones ML T7) and a
publication's override (T8) share them."""

from typing import Annotated

from pydantic import StringConstraints

# The title and attribute values have no fixed ML limit across categories: only a generous cap here.
MAX_TITULO_LENGTH = 255
MAX_ATRIBUTO_VALUE_LENGTH = 255
MAX_DESCRIPCION_LENGTH = 50000  # ML's limit on a description

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
