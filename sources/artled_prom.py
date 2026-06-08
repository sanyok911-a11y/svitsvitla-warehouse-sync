"""ARTLED Prom XML (двомовний UA+RU) — донор RU-описів для KLUS-нових.

XML формат Horoshop YML для маркетплейсу Prom:
  <name>           = RU (основна для Prom)
  <name_ua>        = UA
  <description>    = RU
  <description_ua> = UA
"""
import os
import ssl
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_URL = os.environ.get("ARTLED_PROM_XML_URL") or \
    "https://artled.com.ua/content/export/97fb1dc4f64594a9c6a8005bc0c37e4a.xml"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def fetch(url=None):
    url = url or DEFAULT_URL
    req = urllib.request.Request(url, headers={"User-Agent": "svitsvitla-sync/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
        return r.read()


def parse(xml_bytes):
    """Повертає dict: sku → {name_ru, name_ua, description_ru, description_ua, pictures, url, vendor}."""
    root = ET.fromstring(xml_bytes)
    out = {}
    for off in root.iter("offer"):
        vc = off.findtext("vendorCode")
        if not vc:
            continue
        sku = str(vc).strip()
        pictures = [(p.text or "").strip() for p in off.findall("picture") if p.text]
        out[sku] = {
            "name_ru":        (off.findtext("name") or "").strip() or None,
            "name_ua":        (off.findtext("name_ua") or "").strip() or None,
            "description_ru": (off.findtext("description") or "").strip() or None,
            "description_ua": (off.findtext("description_ua") or "").strip() or None,
            "pictures":       pictures,
            "url":            (off.findtext("url") or "").strip() or None,
            "vendor":         (off.findtext("vendor") or "").strip() or None,
        }
    return out


def load(url=None):
    return parse(fetch(url))
