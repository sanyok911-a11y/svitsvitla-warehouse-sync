"""KeepinCRM HTTP client with retry, throttle, and SKU URL-escaping."""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.keepincrm.com/v1"
USER_AGENT = "ARTLED-WarehouseSync/1.0"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _key():
    k = os.environ.get("KEEPIN_API_KEY")
    if not k:
        raise SystemExit("KEEPIN_API_KEY env var is required")
    return k


def _request(method, path, payload=None, max_retries=6):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Auth-Token", _key())
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as r:
                body = r.read()
                return r.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(min(2 ** attempt, 32))
                continue
            if e.code in (500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 16))
                continue
            return e.code, e.read().decode("utf-8", "ignore")[:300]
        except Exception as ex:
            if attempt == max_retries - 1:
                return 0, f"{type(ex).__name__}: {ex}"
            time.sleep(min(2 ** attempt, 16))
    return 0, "exhausted retries"


def get(path, params=None):
    if params:
        path = f"{path}?{urllib.parse.urlencode(params)}"
    return _request("GET", path)


def patch(path, payload):
    return _request("PATCH", path, payload)


def post(path, payload):
    return _request("POST", path, payload)


def delete(path):
    return _request("DELETE", path)


def quote_sku(sku):
    """SKU зі спецсимволами (пробіл, кома, кирилиця) ламають /materials/sku/{sku}.
    Завжди кодувати з safe=''. Урок з 2026-06-02 (~230 SKU впали без quote)."""
    return urllib.parse.quote(str(sku), safe="")


def patch_by_sku(sku, payload):
    return patch(f"/materials/sku/{quote_sku(sku)}", payload)


def list_all(path, params=None):
    """Pagination wrapper. per_page ігнорується (фіксований 25)."""
    out = []
    page = 1
    while True:
        p = dict(params or {})
        p["page"] = page
        status, resp = get(path, p)
        if status != 200:
            raise RuntimeError(f"{path}?page={page}: {status} {resp}")
        items = resp.get("items", [])
        pg = resp.get("pagination", {})
        if not items:
            break
        out.extend(items)
        if page >= pg.get("total_pages", 1):
            break
        page += 1
    return out


def list_materials():
    return list_all("/materials")


def list_categories():
    return list_all("/materials/categories")


def create_material(payload):
    """Створити новий material. KeepinCRM API НЕ дозволяє ставити custom_fields
    через REST (POST з cf → 500; PATCH cf → 500 або тихо ігнорує). Тому supplier
    у новий запис НЕ пишемо: categoryId «🆕 Нові/{Постачальник}» сама кодує
    звідки товар. Власник руками виставить supplier у UI при перенесенні."""
    payload.pop("custom_fields", None)
    return post("/materials", payload)


def load_ignore_list(path="ignore_new.txt"):
    """Прочитати blacklist sku які НЕ створювати при автоматичному додаванні."""
    out = set()
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line.lower())
    return out
