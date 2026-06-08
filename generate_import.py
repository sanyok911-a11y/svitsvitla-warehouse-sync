#!/usr/bin/env python3
"""Генератор Horoshop YML для імпорту у svitsvitla.com.ua.

Збирає 4 джерела (ML XLSX, KLUS GSheet, Prolum YML, ARTLED XML як донор описів)
+ поточний svitsvitla XML як baseline → генерує import.xml у форматі Horoshop YML.

Логіка:
  - Існуючі (vendorCode матчиться у svitsvitla) → мінімальний <offer> з оновленням price/available
  - Нові (є у постачальника, нема у svitsvitla) → повний <offer>:
      * description + picture з ARTLED якщо є той самий sku, інакше з постачальника
      * категорія — з category_mapping.yaml
  - При невідомій категорії → fallback або pass

CLI:
    python3 generate_import.py                # → ./import.xml
    python3 generate_import.py --out PATH
    python3 generate_import.py --inc-only     # ТІЛЬКИ оновлення (без нових)
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

import yaml

from sources import artled, klus, modernlight, prolum, svitsvitla


def load_mapping(path="category_mapping.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./import.xml")
    ap.add_argument("--inc-only", action="store_true",
                    help="Тільки оновлення цін/наявності існуючих (без нових)")
    ap.add_argument("--no-scrape-prolum", action="store_true")
    args = ap.parse_args()

    mapping = load_mapping()
    lights_cat = mapping.get("lights_category_id")
    fallback_cat = mapping.get("fallback_category_id")
    brand_markup = mapping.get("brand_markup") or {}

    print("[1/5] Fetching svitsvitla baseline…", flush=True)
    svit_offers, svit_cats = svitsvitla.load()
    svit_by_sku = {o["sku"]: o for o in svit_offers}
    print(f"  {len(svit_offers)} існуючих товарів у svitsvitla")

    print("[2/5] Fetching ARTLED XML (донор описів)…", flush=True)
    artled_items = artled.load()
    artled_by_sku = {it["sku"]: it for it in artled_items}
    print(f"  {len(artled_items)} ARTLED товарів (для копіювання описів/фото)")

    print("[3/5] Fetching Modernlight XLSX…", flush=True)
    ml_items = modernlight.load()
    print(f"  {len(ml_items)} Modernlight (після KLUS-prefix skip)")

    print("[4/5] Fetching KLUS Sheet…", flush=True)
    try:
        klus_items = klus.load()
        print(f"  {len(klus_items)} KLUS")
    except Exception as e:
        print(f"  ⚠️ KLUS пропускаємо: {e}")
        klus_items = []

    print("[5/5] Fetching Prolum YML…", flush=True)
    prolum_items = prolum.load(scrape=not args.no_scrape_prolum)
    print(f"  {len(prolum_items)} Prolum")

    def apply_markup(price, vendor):
        if not price or not vendor:
            return price
        add = brand_markup.get(vendor)
        if add:
            return round(float(price) + float(add), 2)
        return price

    # Збираємо всі товари постачальників у єдиний dict sku → record
    all_supplier = {}  # sku → {supplier, price, available, category_from_supplier,
                       #         name, description, pictures, raw_supplier_data}

    for it in ml_items:
        sku = it["sku"]
        section = it.get("section") or ""
        cat = mapping["modernlight"].get(section)
        all_supplier[sku] = {
            "supplier": "Modernlight",
            "sku": sku, "sku_disp": it.get("sku_disp"),
            "name": it.get("title"),
            "vendor": it.get("vendor"),
            "price": apply_markup(it["price"], it.get("vendor")),
            "available": "true" if it["available"] > 0 else "",
            "category_id": cat,
            "section": section,
            "description": it.get("description"),
            "pictures": it.get("pictures") or [],
            "url": it.get("url"),
        }

    for it in klus_items:
        sku = it["sku"]
        all_supplier[sku] = {
            "supplier": "KLUS",
            "sku": sku, "name": it.get("title"),
            "vendor": "KLUS",
            "price": apply_markup(it["price"], "KLUS"),
            "available": "true" if it["available"] > 0 else "",
            "category_id": mapping["klus"].get("default"),
            "description": None,
            "pictures": [],
            "url": None,
        }

    for it in prolum_items:
        sku = it["sku"]
        cat = mapping["prolum"].get(it.get("category_id"))
        all_supplier[sku] = {
            "supplier": "Prolum",
            "sku": sku, "name": it.get("name"),
            "vendor": it.get("vendor"),
            "price": apply_markup(it["price"], it.get("vendor")),
            "available": "true" if it["available"] > 0 else "",
            "category_id": cat,
            "description": it.get("description"),
            "pictures": it.get("pictures") or [],
            "url": it.get("url"),
        }

    # Розділяємо на UPDATE (vendorCode існує у svitsvitla) і NEW (нема).
    # Матчинг у Horoshop — ТІЛЬКИ по vendorCode (= наш CRM sku, унікальний).
    # offer.id/group_id у вихідному XML НЕ передаємо, щоб не плутати Horoshop
    # з його internal ID.
    updates = []
    news = []
    skipped_no_cat = 0
    for sku, sup in all_supplier.items():
        if sku in svit_by_sku:
            updates.append({
                "sku": sku,
                "price": sup["price"],
                "available": sup["available"],
            })
        elif not args.inc_only:
            cat = sup.get("category_id")
            if cat is None:
                if fallback_cat is None:
                    skipped_no_cat += 1
                    continue
                cat = fallback_cat
            news.append({**sup, "category_id": cat})

    print(f"\n=== Plan ===")
    print(f"  UPDATE (існуючі): {len(updates)}")
    print(f"  NEW (додати):     {len(news)}")
    print(f"  Skipped no-cat:   {skipped_no_cat}")

    # Записуємо YML
    write_yml(args.out, svit_cats, updates, news, artled_by_sku)
    print(f"\n✅ Saved → {args.out}")


def write_yml(out_path, svit_cats, updates, news, artled_by_sku):
    """Згенерувати Horoshop YML."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!DOCTYPE yml_catalog SYSTEM "shops.dtd">',
             '<yml_catalog date="now">',
             ' <shop>',
             '  <currencies><currency id="UAH" rate="1"/></currencies>',
             '  <categories>']
    for cid, info in svit_cats.items():
        name = escape(info.get("name") or "")
        parent = info.get("parent_id")
        if parent:
            lines.append(f'   <category id="{cid}" parentId="{parent}">{name}</category>')
        else:
            lines.append(f'   <category id="{cid}">{name}</category>')
    lines.append('  </categories>')
    lines.append('  <offers>')

    # UPDATEs — мінімальний <offer> (тільки price + available), без id/group_id
    # → Horoshop матчить по vendorCode як ключу.
    for u in updates:
        lines.append(f'   <offer available="{u["available"]}">')
        if u["price"] is not None:
            lines.append(f'    <price>{u["price"]}</price>')
            lines.append(f'    <currencyId>UAH</currencyId>')
        lines.append(f'    <vendorCode>{escape(u["sku"])}</vendorCode>')
        lines.append('   </offer>')

    # NEWs — повний <offer>
    for n in news:
        donor = artled_by_sku.get(n["sku"]) or {}
        # Пріоритет: ARTLED donor → supplier-fields
        name = donor.get("name") or n.get("name") or n["sku"]
        url = donor.get("url") or n.get("url") or ""
        description = donor.get("description") or n.get("description") or ""
        pictures = donor.get("pictures") or n.get("pictures") or []
        vendor = donor.get("vendor") or n.get("vendor") or ""

        lines.append(f'   <offer available="{n["available"]}">')
        if url:
            lines.append(f'    <url>{escape(url)}</url>')
        if n["price"]:
            lines.append(f'    <price>{n["price"]}</price>')
            lines.append(f'    <currencyId>UAH</currencyId>')
        if n["category_id"]:
            lines.append(f'    <categoryId>{n["category_id"]}</categoryId>')
        for pic in pictures:
            lines.append(f'    <picture>{escape(pic)}</picture>')
        lines.append(f'    <vendorCode>{escape(n["sku"])}</vendorCode>')
        if vendor:
            lines.append(f'    <vendor>{escape(vendor)}</vendor>')
        lines.append(f'    <name><![CDATA[{name}]]></name>')
        if description:
            lines.append(f'    <description><![CDATA[{description}]]></description>')
        lines.append('   </offer>')

    lines.append('  </offers>')
    lines.append(' </shop>')
    lines.append('</yml_catalog>')

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
