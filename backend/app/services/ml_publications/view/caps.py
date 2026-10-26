"""Caps shared by the Publicaciones ML product resolver and the bulk endpoints it feeds.

Defined once so the two can never drift: the resolver (`view.products.product_ids`) refuses a set over it, and the
bulk endpoints (`productos_shared.ExplicitItemIdsRequest`) refuse an explicit `item_ids` list over it, so every set
the resolver hands out is one the bulk endpoints accept.
"""

# The most products one bulk action may name: Productos' own resolver pages `GET /productos` at most up to 10000 rows
# (`page_size` cap). Over it the request is refused, never truncated (a bulk write over part of the set is the bug).
MAX_EXPLICIT_PRODUCT_IDS = 10000

# The most publications one bulk pause / activate may name (`view.status_targets`). Every one is a separate write to
# ML through the proxy's throttle, so the bound is the time an operator waits, not a query limit.
MAX_STATUS_ITEM_IDS = 500
