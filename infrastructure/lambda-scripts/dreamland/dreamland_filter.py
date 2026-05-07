import argparse
import os
import re
import sys
import csv
import json
import base64
import boto3
import requests
import pandas as pd
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

base_dir = os.path.dirname(__file__)

# Local development: add repo root so `config` package can be found.
# In Lambda, /var/task already contains config/ at the root.
if not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    repo_root = os.path.abspath(os.path.join(base_dir, "..", ".."))
    sys.path.insert(0, repo_root)
    from config.env_utils import load_env
    load_env()

from config.db_connection import get_db_connection

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STOCK_PATH       = os.getenv("DREAMLAND_STOCK_PATH")
IMAGES_URL       = os.getenv("IMAGES_URL")
BASE_URL         = os.getenv("BASE_URL")
IMG_DIR          = os.getenv("DREAMLAND_IMG_PATH", "/tmp/images")
IMAGES_S3_BUCKET = os.getenv("IMAGES_S3_BUCKET")

SUPPLIER_ID              = 2
EXCLUDED_CONDITIONS      = {"REP", "PXN", "EXC", "NXX"}
EXCLUDED_LEADTIME        = {"Repair of the part possible within 14 days"}
PRODUCT_IMAGE_CONDITIONS = {1, 2, 3}  # condition_ids that also populate product_images
MAX_IMAGES_PER_PRICE = 4

timestamp      = datetime.now().strftime("%d%m%Y")
LOGS_DIR       = "/tmp/logs"
STOCK_ERR_FILE = os.path.join(LOGS_DIR, f"error_logs_{timestamp}.csv")
IMG_ERR_FILE   = os.path.join(LOGS_DIR, f"image_errors_{timestamp}.csv")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Brand map
# ---------------------------------------------------------------------------

BRAND_MAP_FILE = os.path.join(base_dir, "brand_map.js")


def load_brand_map(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return {}
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', content)
    return {key.lower(): value for key, value in pairs}


BRAND_MAP = load_brand_map(BRAND_MAP_FILE)


# ===========================================================================
# PHASE 1 — STOCK SYNC
# ===========================================================================

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def clean_reference(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    cleaned = raw_name.strip().upper()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"[^A-Z0-9-]", "", cleaned)
    return cleaned


def normalise_brand(raw_brand: str | None) -> str | None:
    if not raw_brand:
        return None
    cleaned = raw_brand.strip()
    mapped  = BRAND_MAP.get(cleaned.lower())
    return mapped if mapped else cleaned.title()


def normalise_price(price_str: str | None) -> Decimal | None:
    if not price_str:
        return None
    cleaned = str(price_str).strip().replace("€", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def normalise_quantity(raw_stock: str | None) -> int:
    if not raw_stock:
        return 0
    integer_part = raw_stock.split(",", 1)[0]
    return int(integer_part) if integer_part.isdigit() else 0


def parse_leadtime(raw_leadtime: str | None) -> int | None:
    if not raw_leadtime:
        return None
    lead_time_map = {
        "SHIPPING POSSIBLE EVEN TODAY": 2,
        "DELIVERY WITHIN 1-3 DAYS":     3,
        "DELIVERY WITHIN 7 DAYS":       4,
    }
    return lead_time_map.get(raw_leadtime.strip().upper())


def parse_categories(raw_category: str | None) -> dict:
    if not raw_category:
        return {"category": None, "sub_category": None, "sub_sub_category": None}

    parts = [p.strip() for p in raw_category.split("-")]

    def normalize_part(s: str | None) -> str | None:
        if not s:
            return None
        s = s.strip().replace("_", " ")
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r'^\d+(?:[\.,]\d+)?[a-zA-Z]*\s+', '', s).strip()
        if len(s) < 3:
            return None
        if re.match(r'^\d+([a-zA-Z]{1,2})?$', s):
            return None
        if not re.match(r'^[\w\s-]+$', s):
            return None
        if re.match(r'^\d+[a-zA-Z]+', s):
            return None
        tokens       = s.split()
        alpha_tokens = [t for t in tokens if re.fullmatch(r"[A-Za-z]+", t)]
        if alpha_tokens and max(len(t) for t in alpha_tokens) < 3:
            return None
        if any(re.search(r"(?=.*[A-Za-z])(?=.*\d)", t) for t in tokens):
            return None
        return s.title()

    return {
        "category":         normalize_part(parts[0]) if len(parts) > 0 else None,
        "sub_category":     normalize_part(parts[1]) if len(parts) > 1 else None,
        "sub_sub_category": normalize_part(parts[2]) if len(parts) > 2 else None,
    }


def parse_condition(raw_condition: str | None) -> int | None:
    if not raw_condition:
        return None
    condition_map = {"NOU": 1, "NOO": 2, "NOK": 3, "OPR": 4, "PXX": 5}
    return condition_map.get(raw_condition.strip().upper())


def row_context(row: dict) -> dict:
    return {
        "reference": row.get("reference") if row.get("reference") is not None else row.get("NAME"),
        "manufacturer": row.get("brand") if row.get("brand") is not None else row.get("nazev1"),
        "condition": row.get("condition") if row.get("condition") is not None else row.get("CONDITION") if row.get("CONDITION") is not None else row.get("condition_id"),
    }


# ---------------------------------------------------------------------------
# Stock feed fetch
# ---------------------------------------------------------------------------

def fetch_products(path: str) -> list[dict]:
    if not path:
        raise RuntimeError("DREAMLAND_STOCK_PATH is missing or empty.")
    print(f"Reading stock file: {path}")

    with open(path, "rb") as fh:
        raw_body = fh.read()

    def _extract_json_text(decoded: str) -> str:
        cleaned   = decoded.replace("\x00", "").lstrip("\ufeff\ufffd \t\r\n")
        first_obj = cleaned.find("{")
        first_arr = cleaned.find("[")
        starts    = [i for i in (first_obj, first_arr) if i >= 0]
        if not starts:
            raise json.JSONDecodeError("No JSON start found", cleaned, 0)
        return cleaned[min(starts):]

    decoder         = json.JSONDecoder()
    parsed_errors   = []
    decode_attempts = []
    for encoding, mode in (
        ("utf-8",     "strict"),
        ("utf-8-sig", "strict"),
        ("utf-8",     "ignore"),
        ("utf-16",    "ignore"),
    ):
        try:
            decode_attempts.append(raw_body.decode(encoding, errors=mode))
        except UnicodeDecodeError as exc:
            parsed_errors.append(exc)
    raw_no_null = raw_body.replace(b"\x00", b"")
    if raw_no_null != raw_body:
        try:
            decode_attempts.append(raw_no_null.decode("utf-8", errors="ignore"))
        except UnicodeDecodeError as exc:
            parsed_errors.append(exc)

    payload = None
    for decoded in decode_attempts:
        try:
            json_text    = _extract_json_text(decoded)
            payload, _   = decoder.raw_decode(json_text)
            break
        except json.JSONDecodeError as exc:
            parsed_errors.append(exc)

    if payload is None:
        for err in reversed(parsed_errors):
            if isinstance(err, json.JSONDecodeError):
                raise RuntimeError(f"Could not parse JSON from {path}") from err
        raise RuntimeError(f"Could not parse JSON from {path}")

    if not isinstance(payload, dict):
        raise RuntimeError("Stock file JSON root must be an object.")

    products = payload.get("PRODUCTS", [])
    if products is None:
        return []
    if not isinstance(products, list):
        raise RuntimeError("Stock file field 'PRODUCTS' is not a list.")
    return products


# ---------------------------------------------------------------------------
# Stock filtering
# ---------------------------------------------------------------------------

def filter_products(products: list[dict]):
    prepared   = []
    error_logs = []

    for row in products:
        reference = clean_reference(row.get("NAME"))
        if not reference:
            error_logs.append({**row_context(row), "error": "Missing reference"})
            continue

        raw_condition = row.get("CONDITION", "").strip().upper()
        condition_id  = parse_condition(raw_condition)
        if condition_id is None or raw_condition in EXCLUDED_CONDITIONS:
            continue

        leadtime    = row.get("LeadTime", "").strip()
        leadtime_id = parse_leadtime(leadtime)
        if leadtime_id is None or leadtime in EXCLUDED_LEADTIME:
            continue

        price = normalise_price(row.get("YOURPRICE"))
        if price is None or price < Decimal("1"):
            error_logs.append({**row_context(row), "error": "Missing or unparseable price" if price is None else f"Price below minimum: {price}"})
            continue

        categories = parse_categories(row.get("nazev2"))

        prepared.append({
            "reference":        reference,
            "condition_id":     condition_id,
            "brand":            normalise_brand(row.get("nazev1")),
            "category":         categories.get("category") or None,
            "sub_category":     categories.get("sub_category") or None,
            "sub_sub_category": categories.get("sub_sub_category") or None,
            "price":            price,
            "quantity":         normalise_quantity(row.get("STOCK")),
            "supplier_item_id": row.get("ITEM"),
            "lead_time_id":     leadtime_id,
            "lead_time_raw":    leadtime or None,
        })

    return prepared, error_logs


# ---------------------------------------------------------------------------
# DB helpers — stock
# ---------------------------------------------------------------------------

def fetch_one(cursor, query: str, params: tuple):
    cursor.execute(query, params)
    return cursor.fetchone()


def fetch_brand_id(cursor, brand_name: str, brand_cache: dict) -> int:
    key = brand_name.strip().lower()
    if key in brand_cache:
        return brand_cache[key]
    row = fetch_one(cursor, "SELECT id FROM brands WHERE name = %s", (brand_name,))
    if row:
        brand_cache[key] = row["id"]
        return row["id"]
    cursor.execute("INSERT INTO brands (name) VALUES (%s) RETURNING id", (brand_name,))
    brand_id         = cursor.fetchone()["id"]
    brand_cache[key] = brand_id
    return brand_id


def fetch_category_id(cursor, name: str, category_cache: dict) -> int:
    key = name.strip().lower()
    if key in category_cache:
        return category_cache[key]
    row = fetch_one(cursor, "SELECT id FROM categories WHERE name = %s", (name,))
    if row:
        category_cache[key] = row["id"]
        return row["id"]
    cursor.execute("INSERT INTO categories (name) VALUES (%s) RETURNING id", (name,))
    cat_id               = cursor.fetchone()["id"]
    category_cache[key]  = cat_id
    return cat_id


def fetch_product(cursor, reference: str, sku: str):
    cursor.execute(
        "SELECT id, brand_id, category, sub_category, sub_sub_category, sku "
        "FROM products WHERE sku = %s OR reference = %s LIMIT 1",
        (sku, reference),
    )
    return cursor.fetchone()


def insert_product(cursor, reference, brand_id, category_id, sub_category_id, sub_sub_category_id, sku) -> int:
    cursor.execute(
        "INSERT INTO products "
        "(reference, brand_id, category, sub_category, sub_sub_category, sku) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (reference, brand_id, category_id, sub_category_id, sub_sub_category_id, sku),
    )
    return cursor.fetchone()["id"]


def update_product_categories(cursor, product_id, category_id, sub_category_id, sub_sub_category_id):
    cursor.execute(
        "UPDATE products SET category = %s, sub_category = %s, sub_sub_category = %s "
        "WHERE id = %s",
        (category_id, sub_category_id, sub_sub_category_id, product_id),
    )


def update_product_brand(cursor, product_id, brand_id):
    cursor.execute(
        "UPDATE products SET brand_id = %s WHERE id = %s",
        (brand_id, product_id),
    )


def resolve_category_ids(cursor, item: dict, category_cache: dict) -> tuple[int | None, int | None, int | None]:
    category_id = sub_category_id = sub_sub_category_id = None
    if item.get("category"):
        category_id = fetch_category_id(cursor, item["category"], category_cache)
        if item.get("sub_category"):
            sub_category_id = fetch_category_id(cursor, item["sub_category"], category_cache)
        if item.get("sub_sub_category"):
            sub_sub_category_id = fetch_category_id(cursor, item["sub_sub_category"], category_cache)
    return category_id, sub_category_id, sub_sub_category_id


# ---------------------------------------------------------------------------
# Stock processing
# ---------------------------------------------------------------------------

def process_clean_rows(prepared: list[dict], error_logs: list[dict], dry_run: bool = False) -> dict:
    currency = "EUR"
    conn, cursor = get_db_connection()

    brand_cache: dict[str, int]    = {}
    category_cache: dict[str, int] = {}
    processed_keys: set[tuple]     = set()

    counts = {
        "prices_inserted":  0,
        "prices_updated":   0,
        "prices_unchanged": 0,
        "stock_updated":    0,
        "products_created": 0,
        "prices_zeroed":    0,
    }

    try:
        for row in tqdm(prepared, total=len(prepared), desc="Processing stock"):
            try:
                reference    = row["reference"]
                brand_name   = row.get("brand")
                lead_time_id = row.get("lead_time_id")
                condition_id = row["condition_id"]
                quantity     = row["quantity"]
                price        = row["price"]
                warranty     = 6 if condition_id == 5 else 12
                sku          = re.sub(r"[^A-Z0-9]", "", reference.upper())

                product_row = fetch_product(cursor, reference, sku)

                if product_row:
                    product_id       = product_row["id"]
                    current_brand_id = product_row["brand_id"]
                    current_cat_id   = product_row["category"]

                    if not dry_run:
                        if brand_name:
                            expected_brand_id = fetch_brand_id(cursor, brand_name, brand_cache)
                            if current_brand_id != expected_brand_id:
                                update_product_brand(cursor, product_id, expected_brand_id)

                        if row.get("category") and current_cat_id is None:
                            new_cat, new_sub, new_sub_sub = resolve_category_ids(cursor, row, category_cache)
                            update_product_categories(cursor, product_id, new_cat, new_sub, new_sub_sub)
                else:
                    if not brand_name:
                        error_logs.append({**row_context(row), "error": "Can't create new product: missing brand"})
                        continue

                    if not dry_run:
                        brand_id                      = fetch_brand_id(cursor, brand_name, brand_cache)
                        category_id, sub_cat, sub_sub = resolve_category_ids(cursor, row, category_cache)
                        product_id                    = insert_product(
                            cursor, reference, brand_id, category_id, sub_cat, sub_sub, sku
                        )
                    counts["products_created"] += 1

                processed_keys.add((reference, condition_id))

                if dry_run:
                    counts["prices_inserted"] += 1
                    continue

                cursor.execute(
                    "SELECT id, price, quantity FROM prices "
                    "WHERE product_id = %s AND supplier_id = %s "
                    "AND condition_id = %s AND currency = %s",
                    (product_id, SUPPLIER_ID, condition_id, currency),
                )
                existing_price = cursor.fetchone()

                if existing_price:
                    price_changed    = existing_price["price"] != price
                    quantity_changed = int(existing_price["quantity"]) != quantity

                    if price_changed or quantity_changed:
                        cursor.execute(
                            "UPDATE prices SET price = %s, quantity = %s, "
                            "supplier_item_id = %s, lead_time_id = %s, "
                            "updated = CURRENT_TIMESTAMP WHERE id = %s",
                            (price, quantity, row.get("supplier_item_id"),
                             lead_time_id, existing_price["id"]),
                        )
                        if price_changed:
                            counts["prices_updated"] += 1
                        if quantity_changed:
                            counts["stock_updated"] += 1
                    else:
                        counts["prices_unchanged"] += 1
                else:
                    cursor.execute(
                        "INSERT INTO prices "
                        "(product_id, supplier_id, condition_id, supplier_item_id, "
                        "lead_time_id, price, currency, quantity, warranty) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (product_id, SUPPLIER_ID, condition_id, row.get("supplier_item_id"),
                         lead_time_id, price, currency, quantity, warranty),
                    )
                    counts["prices_inserted"] += 1

            except Exception as exc:
                conn.rollback()
                error_logs.append({**row_context(row), "error": f"Processing error: {exc}"})

        # Zero-out pass — rows present in DB but absent from today's feed
        cursor.execute(
            "SELECT pr.id, p.reference, pr.condition_id "
            "FROM prices pr "
            "JOIN products p ON p.id = pr.product_id "
            "WHERE pr.supplier_id = %s AND pr.quantity > 0",
            (SUPPLIER_ID,),
        )
        for row in cursor.fetchall():
            if (row["reference"], row["condition_id"]) not in processed_keys:
                if not dry_run:
                    cursor.execute(
                        "UPDATE prices SET quantity = 0, updated = CURRENT_TIMESTAMP "
                        "WHERE id = %s",
                        (row["id"],),
                    )
                counts["prices_zeroed"] += 1

        if not dry_run:
            conn.commit()

    finally:
        cursor.close()
        conn.close()

    return counts


# ===========================================================================
# PHASE 2 — IMAGE SYNC
# ===========================================================================

# ---------------------------------------------------------------------------
# Generic image detection
# ---------------------------------------------------------------------------

REAL_IMAGE_RE = re.compile(r'.+_[A-Z0-9]{2,4}_\d+\.(jpg|jpeg)$', re.IGNORECASE)

def is_generic_image(decoded_path: str) -> bool:
    filename = decoded_path.replace("/", "\\").split("\\")[-1]
    return not bool(REAL_IMAGE_RE.match(filename))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_b64decode(s: str) -> str | None:
    s = s.strip().replace("\n", "").replace("\r", "")
    missing_padding = len(s) % 4
    if missing_padding:
        s += "=" * (4 - missing_padding)
    try:
        return base64.b64decode(s).decode("utf-16-le")
    except Exception:
        try:
            return base64.b64decode(s).decode("utf-8")
        except Exception as e:
            print(f"    [WARN] Failed to decode base64: {s[:30]}... Error: {e}")
            return None


def log_image_error(supplier_item_id: str | None, url: str, reason: str) -> None:
    file_exists = os.path.exists(IMG_ERR_FILE)
    with open(IMG_ERR_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["supplier_item_id", "url", "reason", "timestamp"])
        writer.writerow([
            supplier_item_id or "",
            url,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ])


# ---------------------------------------------------------------------------
# Image feed streaming
# ---------------------------------------------------------------------------

def build_feed_index(url: str, target_ids: set[str]) -> dict[str, list[str]]:
    """
    Stream the image feed and return a dict mapping each supplier_item_id
    (present in target_ids) to its ordered list of raw base64 links.
    """
    ITEM_REGEX   = re.compile(rb'"Item"\s*:\s*"?(\d+)"?')
    LINK_REGEX   = re.compile(rb'"Link"\s*:\s*"([^"]+)"')
    OBJECT_REGEX = re.compile(rb'\{[^}]*\}')

    index:  dict[str, list[str]] = {}
    buffer = b""
    total  = 0

    print(f"\nStreaming image feed from {IMAGES_URL} ...")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            buffer += chunk.replace(b"\x00", b"")
            for obj_match in OBJECT_REGEX.finditer(buffer):
                obj_bytes  = obj_match.group(0)
                item_match = ITEM_REGEX.search(obj_bytes)
                link_match = LINK_REGEX.search(obj_bytes)
                if not (item_match and link_match):
                    continue
                item_id  = item_match.group(1).decode("ascii")
                raw_link = link_match.group(1).decode("ascii")
                total   += 1
                if total % 200_000 == 0:
                    print(f"  Streamed {total:,} feed entries...")
                if item_id in target_ids:
                    index.setdefault(item_id, []).append(raw_link)
            buffer = buffer[-5000:]

    print(f"  Done. {total:,} total entries — "
          f"{len(index):,} matched target supplier_item_ids.")
    return index


# ---------------------------------------------------------------------------
# DB helpers — images
# ---------------------------------------------------------------------------

def fetch_prices_missing_images(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT
            pr.id               AS price_id,
            pr.product_id,
            pr.condition_id,
            pr.supplier_item_id,
            p.sku
        FROM prices pr
        JOIN products p ON p.id = pr.product_id
        LEFT JOIN price_images pi ON pi.price_id = pr.id
        WHERE pr.supplier_id      = %s
          AND pr.supplier_item_id IS NOT NULL
          AND pi.price_id         IS NULL
        """,
        (SUPPLIER_ID,),
    )
    return cursor.fetchall()


def fetch_existing_image_id(cursor, url: str) -> int | None:
    cursor.execute("SELECT id FROM images WHERE url = %s", (url,))
    row = cursor.fetchone()
    return row["id"] if row else None


def get_next_filename_for_sku(cursor, sku: str) -> str:
    cursor.execute(
        "SELECT alt_text FROM images WHERE alt_text LIKE %s",
        (f"{sku}_%",),
    )
    rows      = cursor.fetchall()
    max_index = 0
    pattern   = re.compile(rf"^{re.escape(sku)}_(\d+)\.JPG$", re.IGNORECASE)

    for row in rows:
        m = pattern.match(row["alt_text"])
        if m:
            max_index = max(max_index, int(m.group(1)))

    if max_index == 0:
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM images WHERE alt_text = %s", (sku,)
        )
        if int(cursor.fetchone()["cnt"]) > 0:
            max_index = 1

    return f"{sku}_{max_index + 1}.JPG"


def image_already_linked_to_price(cursor, image_id: int, price_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM price_images WHERE image_id = %s AND price_id = %s",
        (image_id, price_id),
    )
    return cursor.fetchone() is not None


def product_has_image(cursor, product_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM product_images WHERE product_id = %s LIMIT 1",
        (product_id,),
    )
    return cursor.fetchone() is not None


def write_relationships(cursor, image_id: int, price_records: list[dict]) -> int:
    newly_linked = 0
    for record in price_records:
        price_id     = record["price_id"]
        product_id   = record["product_id"]
        condition_id = record["condition_id"]

        if not image_already_linked_to_price(cursor, image_id, price_id):
            cursor.execute(
                "INSERT INTO price_images (price_id, image_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (price_id, image_id),
            )
            newly_linked += 1

        if condition_id in PRODUCT_IMAGE_CONDITIONS:
            if not product_has_image(cursor, product_id):
                cursor.execute(
                    "INSERT INTO product_images (product_id, image_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (product_id, image_id),
                )

    return newly_linked


# ---------------------------------------------------------------------------
# Per-item image processing
# ---------------------------------------------------------------------------

def process_supplier_item(
    supplier_item_id: str,
    raw_links: list[str],
    price_records: list[dict],
    cursor,
    conn,
    dry_run: bool = False,
) -> dict:
    counts = {"downloaded": 0, "linked": 0, "skipped": 0, "error": 0}

    skus = {r["sku"] for r in price_records}
    if len(skus) > 1:
        print(f"  [WARN] supplier_item_id {supplier_item_id} maps to multiple SKUs: {skus}. "
              f"Using first: {price_records[0]['sku']}")
    sku = price_records[0]["sku"]

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM price_images WHERE price_id = %s",
        (price_records[0]["price_id"],),
    )
    image_count = cursor.fetchone()["cnt"]

    for raw_link in raw_links:
        if image_count >= MAX_IMAGES_PER_PRICE:
            break

        download_url = f"{BASE_URL}{raw_link}"

        decoded_path = safe_b64decode(raw_link)
        if not decoded_path:
            if not dry_run:
                log_image_error(supplier_item_id, download_url, "Failed to decode base64 link")
            counts["error"] += 1
            continue

        if is_generic_image(decoded_path):
            counts["skipped"] += 1
            continue

        # Image URL already in DB — just ensure relationships exist
        existing_image_id = fetch_existing_image_id(cursor, download_url)
        if existing_image_id:
            if dry_run:
                print(f"  [DRY-RUN] Would link existing image "
                      f"| item {supplier_item_id} | {download_url}")
                counts["linked"] += 1
                image_count += 1
            else:
                newly_linked = write_relationships(cursor, existing_image_id, price_records)
                if newly_linked:
                    image_count += 1
                    counts["linked"] += newly_linked
                else:
                    counts["skipped"] += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would download "
                  f"| item {supplier_item_id} | {download_url}")
            counts["downloaded"] += 1
            image_count += 1
            continue

        # Download → insert into images → write relationships
        filename   = get_next_filename_for_sku(cursor, sku)
        local_path = os.path.join(IMG_DIR, filename)

        try:
            resp = requests.get(download_url, timeout=30)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)

            if IMAGES_S3_BUCKET:
                boto3.client("s3").upload_file(
                    local_path, IMAGES_S3_BUCKET, f"images/{filename}"
                )

            cursor.execute(
                "INSERT INTO images (url, alt_text) VALUES (%s, %s) RETURNING id",
                (download_url, filename),
            )
            image_id     = cursor.fetchone()["id"]
            newly_linked = write_relationships(cursor, image_id, price_records)
            image_count += 1
            conn.commit()

            print(f"  ✅ {filename} | linked to {newly_linked} price row(s)")
            counts["downloaded"] += 1

        except Exception as e:
            conn.rollback()
            log_image_error(supplier_item_id, download_url, str(e))
            counts["error"] += 1

    return counts


# ---------------------------------------------------------------------------
# Image sync orchestrator
# ---------------------------------------------------------------------------

def run_image_sync(dry_run: bool = False):
    if not IMAGES_URL or not BASE_URL:
        print("IMAGES_URL or BASE_URL not set — skipping image sync.")
        return

    print("\n" + "=" * 60)
    print("PHASE 2 — Image Sync" + (" [DRY-RUN]" if dry_run else ""))
    print("=" * 60)

    conn, cursor = get_db_connection()

    print("\nFetching prices with missing image relationships...")
    price_rows = fetch_prices_missing_images(cursor)
    print(f"Found {len(price_rows):,} price records missing images.")

    if not price_rows:
        print("Nothing to process.")
        cursor.close()
        conn.close()
        return

    # Group by supplier_item_id
    prices_by_item: dict[str, list[dict]] = defaultdict(list)
    for row in price_rows:
        prices_by_item[str(row["supplier_item_id"])].append(row)

    target_ids = set(prices_by_item.keys())
    print(f"Unique supplier_item_ids to resolve: {len(target_ids):,}")

    # Stream image feed, indexing only our target IDs
    feed_index = build_feed_index(IMAGES_URL, target_ids)

    print(f"\nProcessing {len(feed_index):,} supplier_item_ids found in feed...\n")

    totals      = {"downloaded": 0, "linked": 0, "skipped": 0, "error": 0}
    not_in_feed = 0

    for i, supplier_item_id in enumerate(target_ids, 1):
        if i % 1000 == 0:
            print(f"  Progress: {i:,} / {len(target_ids):,}...")

        raw_links = feed_index.get(supplier_item_id)
        if not raw_links:
            not_in_feed += 1
            continue

        result = process_supplier_item(
            supplier_item_id,
            raw_links,
            prices_by_item[supplier_item_id],
            cursor,
            conn,
            dry_run,
        )
        for key in totals:
            totals[key] += result.get(key, 0)

    cursor.close()
    conn.close()

    print(f"\n{'─' * 60}")
    print(f"Target supplier_item_ids:    {len(target_ids):>10,}")
    print(f"Found in feed:               {len(feed_index):>10,}")
    print(f"Not found in feed:           {not_in_feed:>10,}")
    print(f"{'─' * 40}")
    print(f"{'Would download' if dry_run else 'Downloaded'}:               {totals['downloaded']:>10,}")
    print(f"{'Would link' if dry_run else 'Linked'} (already in DB): {totals['linked']:>10,}")
    print(f"Skipped (generic/duplicate): {totals['skipped']:>10,}")
    print(f"Errors:                      {totals['error']:>10,}")
    if not dry_run and totals["error"] > 0:
        print(f"Error log: {IMG_ERR_FILE}")


# ===========================================================================
# CSV helper
# ===========================================================================

def save_csv(rows: list[dict], filename: str):
    if rows:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        pd.DataFrame(rows).to_csv(filename, index=False)


# ===========================================================================
# MAIN
# ===========================================================================

def lambda_handler(event, _context):
    s3 = boto3.client("s3")

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    local_path = f"/tmp/{os.path.basename(key)}"
    print(f"Downloading s3://{bucket}/{key} to {local_path}")
    s3.download_file(bucket, key, local_path)

    dry_run     = event.get("dry_run", False)
    images_only = event.get("images_only", False)

    stock_counts = {}
    error_logs   = []

    if not images_only:
        try:
            products = fetch_products(local_path)
        except (OSError, RuntimeError) as e:
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

        prepared, error_logs = filter_products(products)
        stock_counts         = process_clean_rows(prepared, error_logs, dry_run=dry_run)
        save_csv(error_logs, STOCK_ERR_FILE)

        if error_logs and not dry_run:
            err_key = f"dreamland/logs/{os.path.basename(STOCK_ERR_FILE)}"
            s3.upload_file(STOCK_ERR_FILE, bucket, err_key)
            print(f"Stock error log uploaded to s3://{bucket}/{err_key}")

    run_image_sync(dry_run=dry_run)

    if not dry_run and os.path.exists(IMG_ERR_FILE):
        img_err_key = f"dreamland/logs/{os.path.basename(IMG_ERR_FILE)}"
        s3.upload_file(IMG_ERR_FILE, bucket, img_err_key)
        print(f"Image error log uploaded to s3://{bucket}/{img_err_key}")

    summary = {"images_only": images_only, "dry_run": dry_run, **stock_counts}
    print("SUMMARY:", json.dumps(summary, indent=2, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}


# ---------------------------------------------------------------------------
# Local entry point
# ---------------------------------------------------------------------------

def main():
    for env_name, env_val in [
        ("DREAMLAND_STOCK_PATH", STOCK_PATH),
        ("IMAGES_URL",           IMAGES_URL),
        ("BASE_URL",             BASE_URL),
    ]:
        if not env_val:
            print(f"Error: {env_name} is not set")
            return

    parser = argparse.ArgumentParser(description="Dreamland Stock + Image Sync")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only — no DB writes or image downloads in either phase.",
    )
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="Skip phase 1 (stock sync) and run phase 2 (image sync) only.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Dreamland Sync")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # PHASE 1 — Stock sync
    # ------------------------------------------------------------------
    if not args.images_only:
        print("\nPHASE 1 — Stock Sync" + (" [DRY-RUN]" if args.dry_run else ""))
        print("─" * 60)

        try:
            products = fetch_products(STOCK_PATH)
        except (OSError, RuntimeError) as e:
            print(f"Error reading stock file: {e}")
            return

        prepared, error_logs = filter_products(products)
        stock_counts         = process_clean_rows(prepared, error_logs, dry_run=args.dry_run)
        save_csv(error_logs, STOCK_ERR_FILE)

        print(f"\nStock sync{'  [DRY-RUN — no writes committed]' if args.dry_run else ''} complete:")
        print(f"  Total fetched:           {len(products):>10,}")
        print(f"  Passed filtering:        {len(prepared):>10,}")
        print(f"  Products created:        {stock_counts['products_created']:>10,}")
        print(f"  Prices inserted:         {stock_counts['prices_inserted']:>10,}")
        print(f"  Prices updated:          {stock_counts['prices_updated']:>10,}")
        print(f"  Stock updated:           {stock_counts['stock_updated']:>10,}")
        print(f"  Prices unchanged:        {stock_counts['prices_unchanged']:>10,}")
        print(f"  Prices zeroed out:       {stock_counts['prices_zeroed']:>10,}")
        print(f"  Errors:                  {len(error_logs):>10,}")
    else:
        print("\n⚡ --images-only: skipping phase 1.")

    # ------------------------------------------------------------------
    # PHASE 2 — Image sync
    # ------------------------------------------------------------------
    run_image_sync(dry_run=args.dry_run)

    print(f"\n{'=' * 60}")
    print(f"All done: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()