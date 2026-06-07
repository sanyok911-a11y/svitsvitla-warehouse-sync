"""svitsvitla.com.ua baseline reader.

Тягне поточний експорт svitsvitla як baseline існуючих товарів —
ми використовуємо vendorCode як ключ, щоб не дублювати товари при імпорті.
"""
import os
import ssl
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_URL = os.environ.get("SVITSVITLA_BASELINE_URL") or \
    "https://svitsvitla.com.ua/content/export/eeedec23d1470b308e1579b3caa36f27.xml"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def fetch(url=None):
    url = url or DEFAULT_URL
    req = urllib.request.Request(url, headers={"User-Agent": "svitsvitla-sync/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        return r.read()


def parse(xml_bytes):
    """Return list of dicts: {sku, offer_id, group_id, price, available, category_id, name, url}."""
    root = ET.fromstring(xml_bytes)
    items = []
    for off in root.iter("offer"):
        vc = off.findtext("vendorCode")
        if not vc:
            continue
        try:
            price = float(off.findtext("price") or 0) or None
        except ValueError:
            price = None
        items.append({
            "sku": str(vc).strip(),
            "offer_id": off.get("id"),
            "group_id": off.get("group_id"),
            "available": off.get("available") == "true",
            "price": price,
            "category_id": off.findtext("categoryId"),
            "name": (off.findtext("name") or "").strip(),
            "url": (off.findtext("url") or "").strip(),
            "vendor": (off.findtext("vendor") or "").strip(),
        })
    return items


def categories(xml_bytes):
    """Return {cat_id: {name, parent_id}}."""
    root = ET.fromstring(xml_bytes)
    out = {}
    for c in root.iter("category"):
        out[c.get("id")] = {"name": c.text, "parent_id": c.get("parentId")}
    return out


def load(url=None):
    xml_bytes = fetch(url)
    return parse(xml_bytes), categories(xml_bytes)
