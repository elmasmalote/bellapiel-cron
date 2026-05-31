import os
import calendar
import logging
from datetime import datetime
import requests
from supabase import create_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL     = os.getenv("SUPABASE_URL")
SUPABASE_KEY     = os.getenv("SUPABASE_SERVICE_KEY")
AGENDA_PRO_KEY   = os.getenv("AGENDA_PRO_API_KEY")
AGENDA_PRO_URL   = "https://agendapro.com/api/public/v1/payments"
BATCH_SIZE       = 500

if not all([SUPABASE_URL, SUPABASE_KEY, AGENDA_PRO_KEY]):
    raise RuntimeError("Faltan variables de entorno: SUPABASE_URL, SUPABASE_SERVICE_KEY, AGENDA_PRO_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_payments(from_date, to_date):
    all_data = []
    page = 1
    headers = {
        "accept": "application/json",
        "authorization": f"Basic {AGENDA_PRO_KEY}"
    }
    while True:
        url = f"{AGENDA_PRO_URL}?from={from_date}&to={to_date}&page={page}"
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            payments = response.json().get("payments", [])
            if not payments:
                break
            all_data.extend(payments)
            logger.info(f"  Página {page}: {len(payments)} registros")
            page += 1
        except requests.RequestException as e:
            logger.error(f"Error en página {page}: {e}")
            break
    return all_data

def parse_payments(payments):
    seen = set()
    rows = []
    for record in payments:
        base = {
            "id":            record.get("id"),
            "payment_date":  record.get("payment_date"),
            "location_name": (record.get("location_name") or "").strip(),
            "amount":        float(record.get("amount") or 0),
            "client_id":     record.get("client", {}).get("id"),
        }
        for booking in record.get("bookings", []):
            row = {**base,
                "service":  (booking.get("service") or "").strip(),
                "cantidad": 1,
                "provider": (booking.get("provider") or "").strip(),
                "price":    float(booking.get("price") or 0),
                "tipo":     "Reserva"
            }
            key = (row["id"], row["service"], row["provider"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
        for mock in record.get("mock_bookings", []):
            row = {**base,
                "service":  (mock.get("service") or "").strip(),
                "cantidad": 1,
                "provider": (mock.get("provider") or "").strip(),
                "price":    float(mock.get("price") or 0),
                "tipo":     "No Reserva"
            }
            key = (row["id"], row["service"], row["provider"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
        for product in record.get("products", []):
            service = f"{product.get('product', '')} {product.get('product_display', '')}".strip()
            row = {**base,
                "service":  service,
                "cantidad": int(product.get("quantity") or 1),
                "provider": str(product.get("seller_details") or "").strip(),
                "price":    float(product.get("price") or 0),
                "tipo":     "Producto"
            }
            key = (row["id"], row["service"], row["provider"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows

def upsert_rows(rows):
    total_ok = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i+BATCH_SIZE]
        try:
            supabase.table("ventas_items").upsert(
                batch, on_conflict="id,service,provider"
            ).execute()
            total_ok += len(batch)
        except Exception as e:
            logger.error(f"Error batch {i//BATCH_SIZE + 1}: {e}")
    return total_ok

def main():
    now = datetime.now()
    year, month = now.year, now.month
    _, last_day = calendar.monthrange(year, month)
    from_date = f"{year}-{month:02d}-01"
    to_date   = f"{year}-{month:02d}-{last_day}"

    logger.info(f"### Sync Bellapiel — {from_date} → {to_date} ###")
    payments = fetch_payments(from_date, to_date)
    logger.info(f"  {len(payments)} pagos descargados")
    rows = parse_payments(payments)
    logger.info(f"  {len(rows)} filas procesadas")
    ok = upsert_rows(rows)
    logger.info(f"  {ok} filas cargadas en Supabase")
    logger.info("### Sync completado ###")

if __name__ == "__main__":
    main()
