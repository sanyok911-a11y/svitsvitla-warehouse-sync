"""ARTLED XML source — синхронізація price + link_url.

XML — це Horoshop YML каталог сайту artled.com.ua.
- vendorCode = наш sku в KeepinCRM
- price = РРЦ (як на сайті)
- url = сторінка товару
"""
import os
import ssl
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_URL = os.environ.get("ARTLED_XML_URL") or \
    "https://artled.com.ua/content/export/1141e8aae8680a65e715d8c6392bdbe6.xml"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def fetch(url=None):
    url = url or DEFAULT_URL
    req = urllib.request.Request(url, headers={"User-Agent": "ARTLED-WarehouseSync/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        return r.read()


def parse(xml_bytes):
    """Return list of dicts: {sku, price, url, name, category_id}."""
    root = ET.fromstring(xml_bytes)
    items = []
    for off in root.iter("offer"):
        vc = off.findtext("vendorCode")
        if not vc:
            continue
        sku = str(vc).strip()
        try:
            price = float(off.findtext("price") or 0) or None
        except ValueError:
            price = None
        pictures = [(p.text or "").strip() for p in off.findall("picture") if p.text]
        items.append({
            "sku": sku,
            "price": price,
            "url": (off.findtext("url") or "").strip() or None,
            "name": (off.findtext("name") or "").strip() or None,
            "category_id": off.findtext("categoryId"),
            "description": (off.findtext("description") or "").strip() or None,
            "pictures": pictures,
            "vendor": (off.findtext("vendor") or "").strip() or None,
        })
    return items


def load(url=None):
    return parse(fetch(url))
