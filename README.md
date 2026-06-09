# svitsvitla.com.ua Warehouse Sync

Генератор Horoshop YML файлу для імпорту в svitsvitla.com.ua.

**Чому окремий проєкт від `artled-warehouse-sync`:**
- svitsvitla НЕ має API (нижчий тариф Horoshop) → шлях не PATCH у CRM, а **генерація YML** + URL-імпорт у Horoshop admin
- Sources reuse: модулі `sources/modernlight.py`, `klus.py`, `prolum.py`, `artled.py` скопійовані з warehouse-sync — однаковий формат, інший спосіб застосування

## Як це працює

1. GHA cron щодоби о 10:00 Київ запускає `generate_import.py`
2. Скрипт тягне 4 джерела + baseline svitsvitla XML
3. Генерує **два** файли у форматі Horoshop YML:
   - `update.xml` — оновлення price/наявності існуючих товарів
   - `new.xml` — нові товари (повний offer, 2 мови)
4. Комітить обидва файли назад у репо
5. **Власник у svitsvitla admin → Імпорт товарів → вставляє URL → "Імпортувати"** (двома окремими імпортами)

URL для імпорту:
- Оновлення: `https://raw.githubusercontent.com/sanyok911-a11y/svitsvitla-warehouse-sync/main/update.xml`
- Нові: `https://raw.githubusercontent.com/sanyok911-a11y/svitsvitla-warehouse-sync/main/new.xml`

**Чому два файли:** Horoshop на кроці імпорту вимагає співпідставлення полів. Якщо у фіді змішані мінімальні offer'и (оновлення) і повні (нові), мапінг плутається. Окремі однорідні файли → стабільне співпідставлення:
- `update.xml`: мапиш лише vendorCode + ціна + наявність
- `new.xml`: повний мапінг з категоріями та двома мовами

## Логіка генератора

- **Існуючі товари** (vendorCode матчиться у svitsvitla) → `update.xml`: мінімальний `<offer>` тільки з оновленням `price` + `available`
- **Нові товари** (є у постачальника, нема у svitsvitla) → `new.xml`: повний `<offer>`:
  - Опис/фото з ARTLED feed якщо є той самий sku (КЛЮС-нові часто є на ARTLED)
  - Дві мови: `<name>`/`<description>` = UA (основна), `<name_ru>`/`<description_ru>` = RU (друга, лише за наявності перекладу)
  - Категорія за `category_mapping.yaml`
  - Якщо немає маппінгу → fallback категорія "🆕 Нові з імпорту без маппінгу"

## Маппінг категорій

Див. `category_mapping.yaml`. Розділи постачальника → svitsvitla cat_id.

## Налаштування

### GitHub Secrets
- `GOOGLE_SA_JSON_B64` — для KLUS Sheet (можна скопіювати з warehouse-sync)
- `MODERNLIGHT_XLSX_URL`, `ARTLED_XML_URL`, `PROLUM_YML_URL`, `PROLUM_COOKIE` (опційно)
- `SVITSVITLA_BASELINE_URL` (опційно — якщо змінить hash svitsvitla експорту)

### Категорії у svitsvitla
1. Створи у Horoshop admin svitsvitla **"Світильники LED"** (нема такої категорії — у ML 39 товарів-світильників)
2. Створи **"🆕 Нові з імпорту без маппінгу"** як fallback
3. Підстав ID у `category_mapping.yaml` (`lights_category_id`, `fallback_category_id`) → commit

## Локальний запуск

```bash
GOOGLE_APPLICATION_CREDENTIALS=~/artled-dashboard-sa.json \
  python3 generate_import.py --out-update ./update.xml --out-new ./new.xml --no-scrape-prolum
```
