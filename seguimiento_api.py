"""
seguimiento_api.py
------------------
Descarga el listado de envíos desde la API v2 de Envíame y lo escribe completo
en la hoja "Seguimiento API", usando como encabezados los mismos campos que
entrega la API (aplanando los objetos anidados como status, customer, etc.).

La hoja es de uso exclusivo de la API: en cada corrida se reescribe entera.
Tu ID viaja en la columna 'imported_id' (lo pones en la Referencia / N° de Envío
de la carga masiva), así que tus hojas de campaña pueden buscar contra esa columna.

Secrets de GitHub (NO escribir en el código):
  - ENVIAME_API_KEY        -> tu API Key (sección "Mi Empresa/Seller" en Envíame)
  - ID_SELLER              -> el ID de tu empresa en Envíame (numérico)
  - GOOGLE_SERVICE_ACCOUNT -> el JSON completo de la cuenta de servicio
  - SHEET_ID               -> el ID del Google Sheet (la planilla nueva)

Opcionales:
  - ENVIAME_BASE_URL  -> por defecto https://api.enviame.io/api
  - HOJA_SALIDA       -> por defecto "Seguimiento API"
  - LIMIT             -> resultados por página (por defecto 100)
  - DIAS_ATRAS        -> si lo defines (ej. 60), solo trae los últimos N días.
  - DELIVERY_STATUS_ID-> filtra por un estado específico de Envíame.
  - VALUE_INPUT       -> "USER_ENTERED" (por defecto, detecta fechas/números) o "RAW".
"""

import os
import json
import time
from datetime import datetime, timedelta

import requests
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

API_KEY = os.environ["ENVIAME_API_KEY"]
ID_SELLER = os.environ["ID_SELLER"]
BASE_URL = os.environ.get("ENVIAME_BASE_URL", "https://api.enviame.io/api")

SHEET_ID = os.environ["SHEET_ID"]
HOJA = os.environ.get("HOJA_SALIDA", "Seguimiento API")

LIMIT = int(os.environ.get("LIMIT", "100"))
DIAS_ATRAS = os.environ.get("DIAS_ATRAS", "").strip()
DELIVERY_STATUS_ID = os.environ.get("DELIVERY_STATUS_ID", "").strip()
VALUE_INPUT = os.environ.get("VALUE_INPUT", "USER_ENTERED")

# Encabezados = campos que entrega la API (objetos anidados aplanados con "_").
ENCABEZADOS = [
    "identifier", "imported_id", "tracking_number",
    "status_id", "status_name", "status_code", "status_info", "status_created_at",
    "customer_full_name", "customer_phone", "customer_email",
    "shipping_full_address", "shipping_place", "shipping_type",
    "country", "carrier", "service",
    "label_pdf", "label_zpl", "label_png",
    "barcodes", "deadline_at", "created_at", "updated_at",
]


def s(v):
    """Convierte cualquier valor a texto seguro para la celda."""
    if v is None:
        return ""
    if isinstance(v, dict):
        # label.ZPL a veces llega como objeto {raw, url}
        if "url" in v:
            return v.get("url") or ""
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def aplanar(e):
    """Convierte un envío de la API en una fila alineada con ENCABEZADOS."""
    status = e.get("status") or {}
    customer = e.get("customer") or {}
    ship = e.get("shipping_address") or {}
    label = e.get("label") or {}
    return [
        s(e.get("identifier")),
        s(e.get("imported_id")),
        s(e.get("tracking_number")),
        s(status.get("id")),
        s(status.get("name")),
        s(status.get("code")),
        s(status.get("info")),
        s(status.get("created_at")),
        s(customer.get("full_name")),
        s(customer.get("phone")),
        s(customer.get("email")),
        s(ship.get("full_address")),
        s(ship.get("place")),
        s(ship.get("type")),
        s(e.get("country")),
        s(e.get("carrier")),
        s(e.get("service")),
        s(label.get("PDF")),
        s(label.get("ZPL")),
        s(label.get("PNG")),
        s(e.get("barcodes")),
        s(e.get("deadline_at")),
        s(e.get("created_at")),
        s(e.get("updated_at")),
    ]


def construir_filtros_fecha():
    if not DIAS_ATRAS:
        return {}
    hoy = datetime.now()
    desde = hoy - timedelta(days=int(DIAS_ATRAS))
    return {"date_from": desde.strftime("%Y-%m-%d"), "date_to": hoy.strftime("%Y-%m-%d")}


# ---------------------------------------------------------------------------
# Descargar todos los envíos (paginado)
# ---------------------------------------------------------------------------

def descargar_envios():
    url = f"{BASE_URL}/s2/v2/companies/{ID_SELLER}/deliveries"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    params_base = {"limit": LIMIT}
    params_base.update(construir_filtros_fecha())
    if DELIVERY_STATUS_ID:
        params_base["delivery_status_id"] = DELIVERY_STATUS_ID

    envios, page = [], 1
    while True:
        params = dict(params_base, page=page)
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        cuerpo = resp.json()
        lote = cuerpo.get("data", []) or []
        envios.extend(lote)
        paginacion = (cuerpo.get("meta") or {}).get("pagination", {}) or {}
        total_pages = paginacion.get("total_pages", 1)
        print(f"  Página {page}/{total_pages} - {len(lote)} envíos")
        if page >= total_pages or not lote:
            break
        page += 1
        time.sleep(0.3)
        if page > 1000:
            print("  Aviso: límite de 1000 páginas alcanzado.")
            break
    return envios


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

def abrir_hoja():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    cliente = gspread.authorize(creds)
    libro = cliente.open_by_key(SHEET_ID)
    try:
        return libro.worksheet(HOJA)
    except gspread.WorksheetNotFound:
        return libro.add_worksheet(title=HOJA, rows=1000, cols=len(ENCABEZADOS))


def main():
    print("Descargando envíos desde Envíame (v2)...")
    envios = descargar_envios()
    print(f"Total descargado: {len(envios)} envíos.")

    filas = [ENCABEZADOS] + [aplanar(e) for e in envios]

    hoja = abrir_hoja()
    hoja.clear()
    hoja.update(values=filas, range_name="A1", value_input_option=VALUE_INPUT)
    print(f"Listo. {len(envios)} envíos escritos en la hoja '{HOJA}'.")


if __name__ == "__main__":
    main()
