"""Modernlight XLSX source.

Колонки фіду svetodiody.com.ua:
  col 0  Артикул
  col 2  Артикул для отображения на сайте  ← обовʼязково використовуємо ОБИДВА для матчингу
  col 5  Название (UA)
  col 7  Бренд
  col 8  Раздел
  col 9  РРЦ
  col 10 Цена
  col 11 Валюта  (UAH або USD)
  col 12 Наличие (текст)
  col 19 Единицы измерения (м / шт. / уп.)
  col 22 Количество

Правила (з памʼяті 2026-06-02):
  - USD ціни множимо на USD_RATE (за умовч. 44.4)
  - cost = «Цена» × курс (закупка)
  - price = «РРЦ» × курс
  - available = «Количество» (число)
  - unit = col 19
  - КОЛІЗІЇ KLUS_* → у KLUS-логіці, ML віддає (skip).
"""
import os

import openpyxl

DEFAULT_URL = os.environ.get("MODERNLIGHT_XLSX_URL") or \
    "https://svetodiody.com.ua/content/export/wholesale/svetodiody.com.ua_eccbc87e4b5ce2fe28308fd9f2a7baf3.xlsx"
USD_RATE = float(os.environ.get("USD_RATE") or "44.4")


def _safe(row, i):
    return row[i] if i < len(row) else None


def parse_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        sku = _safe(row, 0)
        if not sku:
            continue
        sku = str(sku).strip()
        sku_disp = _safe(row, 2)
        sku_disp = str(sku_disp).strip() if sku_disp else None

        # KLUS-* — віддаємо KLUS-у, ML пропускає
        if sku.startswith("KLUS_") or (sku_disp and sku_disp.startswith("KLUS_")):
            continue

        currency = (_safe(row, 11) or "UAH").strip().upper()
        rate = USD_RATE if currency == "USD" else 1.0
        try:
            cost = float(_safe(row, 10) or 0) * rate
            price = float(_safe(row, 9) or 0) * rate
        except (TypeError, ValueError):
            cost = price = 0.0
        try:
            qty = float(_safe(row, 22) or 0)
        except (TypeError, ValueError):
            qty = 0.0

        unit = _safe(row, 19)
        unit = str(unit).strip() if unit else None
        title = _safe(row, 5)
        section = _safe(row, 8)         # "Раздел" — для маппінгу категорії у svitsvitla
        photo = _safe(row, 14)          # "Фото" — основне зображення
        gallery = _safe(row, 15)        # "Галерея" — додаткові
        description = _safe(row, 23)    # "Описание товара (UA)"
        url = _safe(row, 17)            # "Ссылка" на сторінку постачальника
        vendor = _safe(row, 7)          # "Бренд" — для тегу <vendor>

        pictures = []
        if photo:
            pictures.append(str(photo).strip())
        if gallery:
            for p in str(gallery).split(","):
                p = p.strip()
                if p and p not in pictures:
                    pictures.append(p)

        items.append({
            "sku": sku,
            "sku_disp": sku_disp,
            "title": str(title).strip() if title else None,
            "section": str(section).strip() if section else None,
            "vendor": str(vendor).strip() if vendor else None,
            "description": str(description).strip() if description else None,
            "pictures": pictures,
            "url": str(url).strip() if url else None,
            "cost": round(cost, 2) if cost else 0.0,
            "price": round(price, 2) if price else 0.0,
            "available": qty,
            "unit": unit,
            "currency": "UAH",  # після перерахунку завжди UAH
            "supplier": "Modernlight",
        })
    return items


def fetch(url=None, dest="/tmp/modernlight.xlsx"):
    import ssl, urllib.request
    url = url or DEFAULT_URL
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "ARTLED-WarehouseSync/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        with open(dest, "wb") as f:
            f.write(r.read())
    return dest


def load(url=None):
    return parse_xlsx(fetch(url))
