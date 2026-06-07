"""Prolum YML + скрейп дропшип-цін.

- YML: prolum.com.ua/content/export/b535be6f28b2f39c5b8c1b56877635b8.xml — публічний фід (vendorCode, price, available, vendor)
- Дроп-ціни тільки під авторизованою сесією; формула РРЦ×0.70 НЕ годиться (бренди дають різну знижку):
    PROLUM ~30%, MEAN WELL ~10%, інші плавають. → реальний скрейп пошуком.
- ТОЧНА собівартість = дроп × 1.006 (Prolum рахує +0.6% банківської комісії зверху).

Скрейп (з памʼяті 2026-06-03 — повністю валідовано на 1229 кодах):
- platform: Horoshop, https://prolum.com.ua/
- auth: cookie `PHPSESSID` + `challenge_passed=47afe22e2509565e70aa8afde026c8aa96a10f3189d8a79b566bb021c47df7e1` (анти-бот заглушка, статичний хеш)
- search: GET /catalog/search/?q=<urlencoded>
- картка: title=catalogCard-title, дроп=catalogCard-price, РРЦ=catalogCard-rrpPrice, код regex
"""
import os
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_YML = os.environ.get("PROLUM_YML_URL") or \
    "https://prolum.com.ua/content/export/b535be6f28b2f39c5b8c1b56877635b8.xml"
PROLUM_COOKIE = os.environ.get("PROLUM_COOKIE") or None  # "PHPSESSID=...; challenge_passed=..."
PROLUM_BANK_MARKUP = 1.006   # +0.6% банк
PROLUM_RRP_SELL_RATIO = 1.20  # наша роздрібна = РРЦ × 1.20

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def fetch_yml(url=None):
    url = url or DEFAULT_YML
    req = urllib.request.Request(url, headers={"User-Agent": "ARTLED-WarehouseSync/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
        return r.read()


def parse_yml(xml_bytes):
    """Return list of {sku, name, rrp, available, vendor, description, pictures, url, category_id}."""
    root = ET.fromstring(xml_bytes)
    items = []
    seen = set()
    for off in root.iter("offer"):
        vc = off.findtext("vendorCode")
        if not vc:
            continue
        sku = str(vc).strip()
        if sku in seen:
            continue
        seen.add(sku)
        try:
            rrp = float(off.findtext("price") or 0) or None
        except ValueError:
            rrp = None
        av_raw = (off.findtext("available") or "").strip().lower()
        pictures = [(p.text or "").strip() for p in off.findall("picture") if p.text]
        items.append({
            "sku": sku,
            "name": (off.findtext("name") or "").strip() or None,
            "rrp": rrp,
            "available": 1.0 if av_raw == "true" else 0.0,
            "vendor": (off.findtext("vendor") or "").strip() or None,
            "description": (off.findtext("description") or "").strip() or None,
            "pictures": pictures,
            "url": (off.findtext("url") or "").strip() or None,
            "category_id": off.findtext("categoryId"),
        })
    return items


_PRICE_RE = re.compile(r"catalogCard-price[^>]*>\s*([\d\s.,]+)")
_RRP_RE   = re.compile(r"catalogCard-rrpPrice[^>]*>\s*РРЦ:\s*([\d\s.,]+)")


def _scrape_search(sku):
    """Search Prolum and return drop price (UAH) for the first card, or None."""
    if not PROLUM_COOKIE:
        return None
    url = f"https://prolum.com.ua/catalog/search/?q={urllib.parse.quote(str(sku))}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Cookie": PROLUM_COOKIE,
    })
    try:
        with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception:
        return None
    m = _PRICE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def load(scrape=True, max_scrape=None):
    yml_items = parse_yml(fetch_yml())
    items = []
    for it in yml_items:
        rrp = it["rrp"] or 0
        # Sell price = РРЦ × 1.20
        sell = round(rrp * PROLUM_RRP_SELL_RATIO, 2) if rrp else 0.0
        # Drop scrape (if cookie available)
        drop = _scrape_search(it["sku"]) if scrape and PROLUM_COOKIE else None
        cost = round(drop * PROLUM_BANK_MARKUP, 2) if drop else None
        # fallback cost: РРЦ × 0.70 × 1.006 (approx for items not found in scrape)
        if cost is None and rrp:
            cost = round(rrp * 0.70 * PROLUM_BANK_MARKUP, 2)
        items.append({
            "sku": it["sku"],
            "name": it["name"],
            "vendor": it["vendor"],
            "price": sell,
            "cost": cost,
            "available": it["available"],
            "supplier": "Prolum",
            "scraped_drop": drop,
        })
        if max_scrape and len([x for x in items if x["scraped_drop"] is not None]) >= max_scrape:
            scrape = False  # stop scraping further
    return items
