"""KLUS Google Sheet source.

Sheet: 1iO8hnz_6x6LyobyCJ50WMvAIDZf4Q9cyfRdQYOddhBw, tab TDSheet.
Парситься: рядки де кол.0 починається з KLUS_.
Колонки:
  0  Артикул  (KLUS_*)
  3  Назва
  5  Валюта (грн)
  6  Ціна (= РРЦ продажу)
  7  Вільний залишок

Правила:
  - price = Ціна (РРЦ)
  - cost = РРЦ × 0.6  (KLUS дилерська знижка 40%)
  - available = Вільний залишок (negative→0, дробові лишати)
  - supplier = KLUS  (виграє колізії з Modernlight)
"""
import os

SHEET_ID = os.environ.get("KLUS_SHEET_ID") or \
    "1iO8hnz_6x6LyobyCJ50WMvAIDZf4Q9cyfRdQYOddhBw"
SHEET_NAME = "TDSheet"
KLUS_DISCOUNT = 0.6  # cost = price × 0.6


def _client():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "/tmp/sa.json"
    creds = service_account.Credentials.from_service_account_file(
        sa_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def load():
    svc = _client()
    res = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!A1:H10000",
    ).execute()
    rows = res.get("values", [])
    items = []
    for r in rows:
        if not r or not r[0]:
            continue
        sku = str(r[0]).strip()
        if not sku.startswith("KLUS_"):
            continue
        # safe accessors
        def get(i):
            return r[i] if i < len(r) else None

        title = (get(3) or "").strip() or None
        try:
            price = float(str(get(6) or "0").replace(",", ".").replace(" ", ""))
        except ValueError:
            price = 0.0
        try:
            avail_raw = str(get(7) or "0").replace(",", ".").replace(" ", "")
            avail = float(avail_raw)
            if avail < 0:
                avail = 0.0
        except ValueError:
            avail = 0.0
        cost = round(price * KLUS_DISCOUNT, 2) if price else 0.0
        items.append({
            "sku": sku,
            "title": title,
            "price": round(price, 2),
            "cost": cost,
            "available": avail,
            "currency": "UAH",
            "supplier": "KLUS",
        })
    return items
