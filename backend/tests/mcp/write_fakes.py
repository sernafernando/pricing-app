"""A stand-in for the app's endpoints as seen by the MCP write layer (invented data only).

GETs (promos of a publication, markup at a price, the Publicaciones ML page) and the allowlisted writes are answered
from in-memory state; each write changes that state the way the real endpoint would, so the live re-checks, the
read-back and undo see the effect. Stored values read straight from the DB (list prices) use real rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.mcp import loopback
from app.mcp.write import live
from app.models.producto import ProductoERP, ProductoPricing


def promo(promotion_id: str, promotion_type: str, status: str, price: float, **extra: Any) -> dict[str, Any]:
    return {
        "promotion_id": promotion_id,
        "promotion_type": promotion_type,
        "status": status,
        "price": price,
        "original_price": extra.pop("original_price", 1000.0),
        "name": extra.pop("name", f"Promo {promotion_id}"),
        "nuestro_markup": extra.pop("nuestro_markup", 25.0),
        "markup_sell_in_out": extra.pop("markup_sell_in_out", 28.0),
        **extra,
    }


@dataclass
class FakeApp:
    db: Any
    promos: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    markup: float = 30.0
    markup_by_price: dict[float, float] = field(default_factory=dict)
    items_page: list[dict[str, Any]] = field(default_factory=list)
    estados: dict[str, str] = field(default_factory=dict)
    tramos: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    precio_markup: dict[int, float] = field(default_factory=dict)
    fail: dict[tuple[str, str], tuple[int, Any]] = field(default_factory=dict)
    gets: list[tuple[str, dict]] = field(default_factory=list)
    writes: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------ seeding

    def product(self, item_id: int, precio: float, **cuotas: float) -> None:
        self.db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
        self.db.flush()
        self.db.add(
            ProductoPricing(
                item_id=item_id,
                precio_lista_ml=precio,
                precio_3_cuotas=cuotas.get("c3"),
                precio_6_cuotas=cuotas.get("c6"),
                precio_9_cuotas=cuotas.get("c9"),
                precio_12_cuotas=cuotas.get("c12"),
            )
        )
        self.db.commit()

    def pricing(self, item_id: int) -> ProductoPricing:
        self.db.expire_all()
        return self.db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).one()

    def writes_to(self, needle: str) -> list[dict[str, Any]]:
        return [w for w in self.writes if needle in w["path"]]

    # ------------------------------------------------------------ GET

    async def send_request(self, path: str, params: dict, headers: dict) -> tuple[int, bytes]:
        self.gets.append((path, dict(params)))
        if path == "/api/ml-publications/view/items":
            return 200, json.dumps({"total": len(self.items_page), "items": self.items_page}).encode()
        if path == "/api/precios/calcular-markup":
            value = self.markup_by_price.get(float(params["precio"]), self.markup)
            return 200, json.dumps({"markup": value}).encode()
        match = re.match(r"^/api/promociones/item/([^/]+)(/markup)?$", path)
        if match and match.group(2):
            value = self.markup_by_price.get(float(params["price"]), self.markup)
            return 200, json.dumps(
                {"price": params["price"], "nuestro_markup": value, "markup_sell_in_out": value}
            ).encode()
        if match:
            promos = self.promos.get(match.group(1), [])
            return 200, json.dumps({"mla": match.group(1), "count": len(promos), "promotions": promos}).encode()
        return 404, json.dumps({"detail": "no fake for " + path}).encode()

    # ------------------------------------------------------------ writes

    async def send_write(self, method: str, path: str, params: dict, body: Any, headers: dict) -> tuple[int, bytes]:
        assert loopback.write_allowed(method, path), (method, path)
        self.writes.append({"method": method, "path": path, "params": dict(params), "body": body})
        for (m, needle), answer in self.fail.items():
            if m == method and needle in path:
                return answer[0], json.dumps(answer[1]).encode()
        status, payload = self._effect(method, path, params, body)
        return status, json.dumps(payload).encode()

    def _effect(self, method: str, path: str, params: dict, body: Any) -> tuple[int, Any]:
        match = re.match(r"^/api/promociones/item/([^/]+)$", path)
        if match:
            pid = body["promotion_id"] if method == "POST" else params["promotion_id"]
            for p in self.promos.get(match.group(1), []):
                if p["promotion_id"] == pid:
                    p["status"] = "started" if method == "POST" else "candidate"
            return 200, {"submitted": True, "status": "submitted"}
        match = re.match(r"^/api/ml-publications/items/([^/]+)/status$", path)
        if match:
            self.estados[match.group(1)] = body["status"]
            return 200, {"status": "submitted", "message": None}
        if path == "/api/precios/set-rapido":
            pricing = self.pricing(int(params["item_id"]))
            pricing.precio_lista_ml = float(params["precio"])
            self.db.commit()
            return 200, {"item_id": params["item_id"]}
        if path == "/api/precios/set-cuota":
            pricing = self.pricing(int(params["item_id"]))
            value = float(params["precio"]) or None
            if params["tipo_cuota"] == "clasica":
                pricing.precio_lista_ml = value
            else:
                setattr(pricing, f"precio_{params['tipo_cuota']}_cuotas", value)
            self.db.commit()
            return 200, {"item_id": params["item_id"]}
        if path == "/api/precios/aplicar-markup-masivo":
            item_id = body["item_ids"][0]
            pricing = self.pricing(item_id)
            pricing.precio_lista_ml = self.precio_markup[item_id]
            self.db.commit()
            return 200, {"total": 1, "ok": 1, "errores": 0, "resultados": [{"item_id": item_id, "ok": True}]}
        match = re.match(r"^/api/pxq/([^/]+)/tiers/(\d+)$", path)
        if match:
            for tier in self.tramos.get(match.group(1), []):
                if tier["id"] == int(match.group(2)):
                    tier["precio_unitario"] = body["precio_unitario"]
            return 200, {"id": int(match.group(2))}
        if re.match(r"^/api/pxq/([^/]+)/sync$", path):
            return 200, {"synced": True, "status": "synced"}
        return 404, {"detail": "no fake"}

    # ------------------------------------------------------------ install

    def install(self, monkeypatch, writes: bool = True) -> FakeApp:
        monkeypatch.setattr(loopback, "send_request", self.send_request)
        if writes:
            monkeypatch.setattr(loopback, "send_write", self.send_write)
        monkeypatch.setattr(live, "estados", lambda db, mlas: {m: self.estados[m] for m in mlas if m in self.estados})
        monkeypatch.setattr(live, "tramos", lambda db, mla: [dict(t) for t in self.tramos.get(mla, [])])
        monkeypatch.setattr(live, "markup_mayorista", lambda db, mla, tier_id, precio: self.markup)
        monkeypatch.setattr(live, "precio_por_markup", lambda db, item_id, markup: self.precio_markup.get(item_id))
        return self
