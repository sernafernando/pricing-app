"""
Google Sheets sync service for Caja module.

One-time historical import from the existing cash tracking spreadsheet.
Maps sheet tabs to cajas, parses Argentine date/number formats,
detects duplicates by (caja_id, fecha, detalle, tipo, monto),
and bulk-inserts with balance recalculation.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.caja import Caja, CajaMovimiento
from app.models.empresa import Empresa

# Tab name → caja metadata.
SHEET_TAB_MAPPING: dict[str, dict] = {
    "CAJA $ PASTORIZA": {"empresa_nombre": "Pastoriza", "moneda": "ARS"},
    "CAJA USD PASTORIZA": {"empresa_nombre": "Pastoriza", "moneda": "USD"},
    "CAJA $ GRUPO GAUSS": {"empresa_nombre": "Grupo Gauss", "moneda": "ARS"},
}

# Only import data from this year. The sheet has historical data without
# year in dates (just dd/mm), so we can't reliably infer older years.
SYNC_YEAR: int = 2026


class SyncResult:
    """Accumulates sync statistics."""

    def __init__(self) -> None:
        self.total_procesadas: int = 0
        self.nuevas: int = 0
        self.duplicadas_saltadas: int = 0
        self.errores: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "total_procesadas": self.total_procesadas,
            "nuevas": self.nuevas,
            "duplicadas_saltadas": self.duplicadas_saltadas,
            "errores": self.errores,
        }


class CajaSheetsSync:
    """Servicio de sincronización Google Sheets → Caja."""

    def __init__(self, db: Session):
        self.db = db

    def sincronizar(self) -> dict:
        """
        Main sync entrypoint. Reads all configured tabs from the spreadsheet,
        parses rows, detects duplicates, bulk-inserts, and recalculates balances.
        """
        import gspread
        from google.oauth2.service_account import Credentials

        sheet_id = settings.GOOGLE_CAJA_ID
        if not sheet_id:
            raise ValueError("GOOGLE_CAJA_ID environment variable is not configured")

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        try:
            creds = Credentials.from_service_account_file(settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(sheet_id)
        except Exception as e:
            raise ConnectionError(f"Could not connect to Google Sheets: {e}")

        result = SyncResult()

        for tab_name, meta in SHEET_TAB_MAPPING.items():
            try:
                worksheet = spreadsheet.worksheet(tab_name)
            except gspread.WorksheetNotFound:
                result.errores.append({"tab": tab_name, "error": f"Tab '{tab_name}' not found in spreadsheet"})
                continue

            caja = self._get_or_create_caja(tab_name, meta)
            self._process_tab(worksheet, caja, result)

        self.db.flush()
        return result.to_dict()

    def _get_or_create_caja(self, tab_name: str, meta: dict) -> Caja:
        """Gets existing caja or creates it."""
        empresa = self.db.query(Empresa).filter(Empresa.nombre.ilike(f"%{meta['empresa_nombre']}%")).first()
        empresa_id = empresa.id if empresa else 1  # fallback

        caja = self.db.query(Caja).filter(Caja.nombre == tab_name, Caja.empresa_id == empresa_id).first()
        if not caja:
            caja = Caja(
                nombre=tab_name,
                empresa_id=empresa_id,
                moneda=meta["moneda"],
                saldo_inicial=Decimal("0"),
                saldo_actual=Decimal("0"),
            )
            self.db.add(caja)
            self.db.flush()
        return caja

    def _process_tab(self, worksheet, caja: Caja, result: SyncResult) -> None:
        """
        Processes rows from a single worksheet tab.

        Only imports rows whose parsed year == SYNC_YEAR.
        Dates without explicit year (dd/mm) are assumed to be SYNC_YEAR.
        Dates with explicit year that differs from SYNC_YEAR are skipped.
        """
        all_values = worksheet.get_all_values()
        if len(all_values) < 2:
            return

        # Find header row (look for FECHA)
        header_idx = 0
        for i, row in enumerate(all_values):
            upper_row = [c.strip().upper() for c in row]
            if "FECHA" in upper_row:
                header_idx = i
                break

        headers = [h.strip().upper() for h in all_values[header_idx]]

        # Find column indexes.
        # Some tabs have an empty or whitespace-only header for the date column
        # (the actual dates start in row 1). Fall back to column 0 for FECHA.
        col_fecha = headers.index("FECHA") if "FECHA" in headers else None
        col_detalle = headers.index("DETALLE") if "DETALLE" in headers else None
        col_ingresos = headers.index("INGRESOS") if "INGRESOS" in headers else None
        col_egresos = headers.index("EGRESOS") if "EGRESOS" in headers else None

        # Fallback: if FECHA column not found but DETALLE exists,
        # assume column 0 is the date (common in hand-made sheets).
        if col_fecha is None and col_detalle is not None:
            col_fecha = 0

        if col_fecha is None or col_detalle is None:
            result.errores.append(
                {
                    "tab": caja.nombre,
                    "error": "Missing FECHA or DETALLE columns",
                }
            )
            return

        # Load existing movements for duplicate detection
        existing_keys = set()
        existing_movs = (
            self.db.query(
                CajaMovimiento.fecha,
                CajaMovimiento.detalle,
                CajaMovimiento.tipo,
                CajaMovimiento.monto,
            )
            .filter(CajaMovimiento.caja_id == caja.id)
            .all()
        )
        for m in existing_movs:
            existing_keys.add((m.fecha, m.detalle, m.tipo, float(m.monto)))

        # Process data rows
        new_movements: list[dict] = []
        skipped_other_year: int = 0

        for row_num, row in enumerate(all_values[header_idx + 1 :], start=header_idx + 2):
            result.total_procesadas += 1

            # Get cell values
            fecha_str = row[col_fecha].strip() if col_fecha < len(row) else ""
            detalle = row[col_detalle].strip() if col_detalle < len(row) else ""
            ingreso_str = row[col_ingresos].strip() if col_ingresos is not None and col_ingresos < len(row) else ""
            egreso_str = row[col_egresos].strip() if col_egresos is not None and col_egresos < len(row) else ""

            if not fecha_str or not detalle:
                continue

            # Parse date — dates without year default to SYNC_YEAR
            fecha, has_explicit_year = self._parse_fecha(fecha_str, default_year=SYNC_YEAR)
            if not fecha:
                result.errores.append({"row": row_num, "error": f"Invalid date format: '{fecha_str}'"})
                continue

            # Only import rows from SYNC_YEAR
            if fecha.year != SYNC_YEAR:
                skipped_other_year += 1
                continue

            # Parse amounts
            ingreso = self._parse_monto(ingreso_str)
            egreso = self._parse_monto(egreso_str)

            if not ingreso and not egreso:
                continue  # skip empty amounts

            if ingreso and ingreso > 0:
                tipo = "ingreso"
                monto = ingreso
            elif egreso and egreso > 0:
                tipo = "egreso"
                monto = egreso
            else:
                continue

            # Duplicate check
            key = (fecha, detalle, tipo, monto)
            if key in existing_keys:
                result.duplicadas_saltadas += 1
                continue

            existing_keys.add(key)
            new_movements.append(
                {
                    "caja_id": caja.id,
                    "fecha": fecha,
                    "detalle": detalle,
                    "tipo": tipo,
                    "monto": Decimal(str(monto)),
                    "origen": "sync",
                }
            )

        if skipped_other_year > 0:
            result.errores.append(
                {
                    "tab": caja.nombre,
                    "info": f"Skipped {skipped_other_year} rows with explicit year != {SYNC_YEAR}",
                }
            )

        # Bulk insert new movements (without saldo_posterior yet)
        if new_movements:
            # Sort chronologically for proper balance calculation
            new_movements.sort(key=lambda m: (m["fecha"], 0))
            for mov_data in new_movements:
                mov = CajaMovimiento(
                    caja_id=mov_data["caja_id"],
                    fecha=mov_data["fecha"],
                    detalle=mov_data["detalle"],
                    tipo=mov_data["tipo"],
                    monto=mov_data["monto"],
                    saldo_posterior=Decimal("0"),  # will be recalculated
                    origen=mov_data["origen"],
                )
                self.db.add(mov)
            self.db.flush()
            result.nuevas += len(new_movements)

            # Recalculate running balance for the entire caja
            self._recalculate_balance(caja)

    def _recalculate_balance(self, caja: Caja) -> None:
        """Recalculates saldo_posterior for all movements and updates caja.saldo_actual."""
        saldo = Decimal(str(caja.saldo_inicial))
        movimientos = (
            self.db.query(CajaMovimiento)
            .filter(CajaMovimiento.caja_id == caja.id)
            .order_by(CajaMovimiento.fecha.asc(), CajaMovimiento.id.asc())
            .all()
        )
        for mov in movimientos:
            monto = Decimal(str(mov.monto))
            if mov.tipo == "ingreso":
                saldo += monto
            else:
                saldo -= monto
            mov.saldo_posterior = saldo
        caja.saldo_actual = saldo

    @staticmethod
    def _parse_fecha(fecha_str: str, default_year: int = 2023) -> tuple[Optional[date], bool]:
        """
        Parses dates in Argentine formats.

        Returns (parsed_date, has_explicit_year):
        - dd/mm/yyyy → (date, True)
        - dd/mm/yy   → (date, True)  (yy + 2000)
        - dd/mm      → (date with default_year, False)
        - invalid    → (None, False)

        The caller uses has_explicit_year to decide whether to apply
        chronological year-inference logic.
        """
        fecha_str = fecha_str.strip()
        if not fecha_str:
            return None, False

        parts = fecha_str.split("/")
        if len(parts) < 2:
            return None, False

        try:
            day = int(parts[0])
            month = int(parts[1])
            has_explicit_year = False
            if len(parts) >= 3 and parts[2].strip():
                year = int(parts[2])
                if year < 100:
                    year += 2000
                has_explicit_year = True
            else:
                year = default_year

            return date(year, month, day), has_explicit_year
        except (ValueError, IndexError):
            return None, False

    @staticmethod
    def _parse_monto(monto_str: str) -> Optional[float]:
        """
        Parses amounts in Argentine format:
        - Dot as thousands separator
        - Comma as decimal separator
        - Handles $, spaces, %
        """
        if not monto_str or not monto_str.strip():
            return None

        cleaned = monto_str.strip()
        cleaned = cleaned.replace("$", "").replace(" ", "").replace("%", "")
        # Argentine: dot=thousands, comma=decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")

        try:
            val = float(cleaned)
            return val if val > 0 else None
        except (ValueError, InvalidOperation):
            return None
