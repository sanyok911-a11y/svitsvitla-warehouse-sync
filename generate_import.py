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

Вихід — ДВА файли (Horoshop імпортує їх окремими кроками з різним мапінгом):
    update.xml — оновлення price/наявності існуючих (мінімальний offer)
    new.xml    — нові товари (повний offer + категорії, 2 мови)

CLI:
    python3 generate_import.py                       # → ./update.xml + ./new.xml
    python3 generate_import.py --out-update U --out-new N
    python3 generate_import.py --inc-only            # ТІЛЬКИ update.xml (без нових)
"""
import argparse
import json
import os
import re
import sys
from xml.sax.saxutils import escape

import yaml

from sources import artled, artled_prom, klus, modernlight, prolum, svitsvitla


def load_mapping(path="category_mapping.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-update", default="./update.xml",
                    help="Файл оновлення цін/наявності існуючих товарів")
    ap.add_argument("--out-new", default="./new.xml",
                    help="Файл нових товарів (повний offer)")
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

    print("[2/5] Fetching ARTLED XML (донор UA)…", flush=True)
    artled_items = artled.load()
    artled_by_sku = {it["sku"]: it for it in artled_items}
    print(f"  {len(artled_items)} ARTLED UA")

    print("[2b/5] Fetching ARTLED Prom XML (донор RU+UA)…", flush=True)
    try:
        artled_prom_by_sku = artled_prom.load()
        print(f"  {len(artled_prom_by_sku)} ARTLED Prom (двомовний)")
    except Exception as e:
        print(f"  ⚠️ Prom-донор пропускаємо: {e}")
        artled_prom_by_sku = {}

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
            "name_ua": it.get("title"),
            "name_ru": it.get("title_ru"),
            "vendor": it.get("vendor"),
            "price": apply_markup(it["price"], it.get("vendor")),
            "available": "true" if it["available"] > 0 else "",
            "category_id": cat,
            "section": section,
            "description_ua": it.get("description"),
            "description_ru": it.get("description_ru"),
            "pictures": it.get("pictures") or [],
            "url": it.get("url"),
        }

    for it in klus_items:
        sku = it["sku"]
        all_supplier[sku] = {
            "supplier": "KLUS",
            "sku": sku, "name_ua": it.get("title"), "name_ru": None,
            "vendor": "KLUS",
            "price": apply_markup(it["price"], "KLUS"),
            "available": "true" if it["available"] > 0 else "",
            "category_id": mapping["klus"].get("default"),
            "description_ua": None, "description_ru": None,
            "pictures": [],
            "url": None,
        }

    for it in prolum_items:
        sku = it["sku"]
        cat = mapping["prolum"].get(it.get("category_id"))
        all_supplier[sku] = {
            "supplier": "Prolum",
            "sku": sku, "name_ua": it.get("name"), "name_ru": None,
            "vendor": it.get("vendor"),
            "price": apply_markup(it["price"], it.get("vendor")),
            "available": "true" if it["available"] > 0 else "",
            "category_id": cat,
            "description_ua": it.get("description"), "description_ru": None,
            "pictures": it.get("pictures") or [],
            "url": it.get("url"),
        }

    # Виключаємо мерч/демо/тех.позиції (category_mapping.yaml → exclude_*).
    excl_skus = {str(s) for s in (mapping.get("exclude_skus") or [])}
    excl_pats = [p.lower() for p in (mapping.get("exclude_name_patterns") or [])]

    def is_excluded(sku, sup):
        if str(sku) in excl_skus:
            return True
        nm = (sup.get("name_ua") or "").lower()
        return any(p in nm for p in excl_pats)

    n_before = len(all_supplier)
    all_supplier = {s: sup for s, sup in all_supplier.items() if not is_excluded(s, sup)}
    n_excluded = n_before - len(all_supplier)

    # Уточнення категорії за назвою (category_mapping.yaml → recategorize):
    # напр. трекові світильники з секції 1321 → 1323, компоненти лишаються в 1321.
    recat_rules = mapping.get("recategorize") or []
    n_recat = 0

    def _norm(s):
        # нормалізуємо різні варіанти апострофа → ' для надійного матчингу
        return re.sub(r"['’ʼ`´‘]", "'", (s or "")).strip().lower()

    for sup in all_supplier.values():
        nm = _norm(sup.get("name_ua"))
        for rule in recat_rules:
            if sup.get("category_id") != rule.get("from"):
                continue
            contains = [_norm(k) for k in (rule.get("if_name_contains") or [])]
            starts = [_norm(k) for k in (rule.get("if_name_startswith") or [])]
            if any(k in nm for k in contains) or any(nm.startswith(k) for k in starts):
                sup["category_id"] = rule.get("to")
                n_recat += 1
                break

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
    print(f"  Excluded (мерч/демо): {n_excluded}")
    print(f"  Recategorized:        {n_recat}")
    print(f"  UPDATE (існуючі):     {len(updates)}")
    print(f"  NEW (додати):         {len(news)}")
    print(f"  Skipped no-cat:       {skipped_no_cat}")

    # Записуємо ДВА окремі YML — Horoshop імпортує їх різними кроками
    # з різним мапінгом полів (update = price/наявність, new = повний товар).
    write_yml_update(args.out_update, updates)
    print(f"\n✅ Update XML → {args.out_update}  ({len(updates)} offers)")

    if not args.inc_only:
        # fallback-категорія прихована в svitsvitla → нема в експорті; додаємо
        # її назву у блок <categories>, щоб фід був самодостатнім.
        fb_name = mapping.get("fallback_category_name")
        if fallback_cat and fb_name and fallback_cat not in svit_cats:
            svit_cats[fallback_cat] = {"name": fb_name, "parent_id": None}
        write_yml_new(args.out_new, svit_cats, news, artled_by_sku, artled_prom_by_sku)
        print(f"✅ New XML    → {args.out_new}  ({len(news)} offers)")


_HEAD = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!DOCTYPE yml_catalog SYSTEM "shops.dtd">',
         '<yml_catalog date="now">',
         ' <shop>',
         '  <currencies><currency id="UAH" rate="1"/></currencies>']
_FOOT = ['  </offers>', ' </shop>', '</yml_catalog>']


def write_yml_update(out_path, updates):
    """update.xml — ТІЛЬКИ оновлення price/наявності існуючих товарів.

    Однорідний мінімальний <offer> (vendorCode + price + available), без
    категорій/назв/описів. Horoshop матчить по vendorCode як ключу, тому
    на кроці імпорту треба зіставити лише 3 поля — мапінг тривіальний.
    """
    lines = list(_HEAD)
    lines.append('  <offers>')
    for u in updates:
        lines.append(f'   <offer available="{u["available"]}">')
        if u["price"] is not None:
            lines.append(f'    <price>{u["price"]}</price>')
            lines.append(f'    <currencyId>UAH</currencyId>')
        lines.append(f'    <vendorCode>{escape(u["sku"])}</vendorCode>')
        lines.append('   </offer>')
    lines.extend(_FOOT)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_yml_new(out_path, svit_cats, news, artled_by_sku, artled_prom_by_sku):
    """new.xml — ТІЛЬКИ нові товари: повний <offer> + блок категорій.

    Дві мови у канонічному форматі Horoshop:
      <name>     / <description>     — основна мова (UA, без суфікса, як у експорті svitsvitla)
      <name_ru>  / <description_ru>  — друга мова (RU, суфікс коду мови)
    """
    lines = list(_HEAD)
    lines.append('  <categories>')
    for cid, info in svit_cats.items():
        name = escape(info.get("name") or "")
        parent = info.get("parent_id")
        if parent:
            lines.append(f'   <category id="{cid}" parentId="{parent}">{name}</category>')
        else:
            lines.append(f'   <category id="{cid}">{name}</category>')
    lines.append('  </categories>')
    lines.append('  <offers>')

    # Пріоритет джерел: ARTLED Prom (UA+RU пари) → ARTLED UA → постачальник
    # (ML має RU, KLUS/Prolum — UA only).
    for n in news:
        prom = artled_prom_by_sku.get(n["sku"]) or {}
        donor = artled_by_sku.get(n["sku"]) or {}

        # UA — основна: prom_ua → ARTLED-name → supplier name_ua
        name_ua = prom.get("name_ua") or donor.get("name") or n.get("name_ua") or n["sku"]
        # RU — друга: prom_ru → supplier name_ru (ML має); інакше не пишемо тег
        name_ru = prom.get("name_ru") or n.get("name_ru")

        desc_ua = prom.get("description_ua") or donor.get("description") or n.get("description_ua") or ""
        desc_ru = prom.get("description_ru") or n.get("description_ru")

        url = donor.get("url") or n.get("url") or prom.get("url") or ""
        pictures = (donor.get("pictures") or n.get("pictures") or prom.get("pictures") or [])
        vendor = donor.get("vendor") or n.get("vendor") or prom.get("vendor") or ""

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
        # <name> = UA (основна), <name_ru> = RU (друга) — лише якщо є переклад
        lines.append(f'    <name><![CDATA[{name_ua}]]></name>')
        if name_ru and name_ru != name_ua:
            lines.append(f'    <name_ru><![CDATA[{name_ru}]]></name_ru>')
        if desc_ua:
            lines.append(f'    <description><![CDATA[{desc_ua}]]></description>')
        if desc_ru and desc_ru != desc_ua:
            lines.append(f'    <description_ru><![CDATA[{desc_ru}]]></description_ru>')
        lines.append('   </offer>')

    lines.extend(_FOOT)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
