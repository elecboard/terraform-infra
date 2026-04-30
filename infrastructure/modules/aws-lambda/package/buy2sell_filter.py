import re
import pandas as pd
from datetime import datetime
import os
from tqdm import tqdm
from decimal import Decimal, InvalidOperation

from config.db_connection import get_db_connection

base_dir = os.path.dirname(__file__)

# Configuration
CSV_FILE = os.getenv("B2S_STOCK_PATH")
SUPPLIER_ID = 3  # Buy2Sell
DEFAULT_WARRANTY = 12
DEFAULT_LEAD_TIME_ID = 3  # 3-5d
DEFAULT_CURRENCY = "EUR"

timestamp = datetime.now().strftime("%d%m%Y")
LOGS_DIR = "/tmp/logs"
ERROR_LOGS_FILE = os.path.join(LOGS_DIR, f"b2s_error_logs_{timestamp}.csv")
BRAND_MAP_FILE = os.path.join(base_dir, "brand_map.js")

os.makedirs(LOGS_DIR, exist_ok=True)


# REFERENCE CLEANING
def is_unknown_value(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"unknown", "nan", "none", "n/a"}


def clean_reference(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    if is_unknown_value(raw_name):
        return ""

    cleaned = raw_name.strip().upper()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
    if cleaned == "UNKNOWN":
        return ""
    return cleaned


def build_sku(reference: str) -> str:
    if not reference:
        return ""
    cleaned = re.sub(r"[^A-Z0-9]", "", reference.upper())
    if not cleaned or cleaned == "UNKNOWN":
        return ""
    return cleaned


# BRAND MAP LOADING
def load_brand_map(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except FileNotFoundError:
        print(f"Warning: Brand map file not found at {path}")
        return {}

    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', content)
    return {key.lower(): value for key, value in pairs}


BRAND_MAP = load_brand_map(BRAND_MAP_FILE)

# COLUMN NORMALISATION
COLUMN_MAP = {
    "Part_Number": "reference",
    "Brand": "brand",
    "QTY": "quantity",
    "Description": "description",
    "Price": "price",
    "Category": "category",
    "Product_condition": "condition",
    "Weight": "weight",
    "Image_url": "image_url",
    "GTIN": "gtin",
}

COLUMN_MAP_LOWER = {key.lower(): value for key, value in COLUMN_MAP.items()}


def normalise_columns(product: dict) -> dict:
    normalised: dict = {}
    for key, value in product.items():
        if pd.isna(value):
            value = None

        if isinstance(key, str):
            key_clean = key.strip()
            key_lower = key_clean.lower()
            mapped = COLUMN_MAP_LOWER.get(key_lower)
            if mapped:
                if mapped not in normalised or normalised[mapped] in (None, ""):
                    normalised[mapped] = value
            else:
                normalised[key] = value
        else:
            normalised[key] = value
    return normalised


# BRAND NORMALISATION
def normalise_brand(raw_brand: str | None) -> str | None:
    if not raw_brand:
        return None
    cleaned = raw_brand.strip()
    key = cleaned.lower()
    if key in BRAND_MAP:
        mapped = BRAND_MAP[key]
        if not mapped or not mapped.strip():
            return None
        return mapped
    return cleaned.title()


# GTIN NORMALISATION
def normalise_gtin(raw_gtin: str | None) -> str | None:
    if not raw_gtin:
        return None

    gtin_str = str(raw_gtin).strip()

    if gtin_str.lower() in ('unknown', 'nan', 'none', ''):
        return None

    if not gtin_str.isdigit():
        return None

    if len(gtin_str) not in (8, 12, 13, 14):
        return None

    return gtin_str[:14]


# PRICE NORMALISATION
def normalise_price(price_str: str | None) -> Decimal | None:
    if not price_str:
        return None

    price_str = str(price_str).strip()
    if ":" in price_str:
        price_str = price_str.split(":")[0]

    cleaned = price_str.replace("€", "").replace(" ", "")

    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        price = Decimal(cleaned)
        return price.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


# QUANTITY NORMALISATION
def normalise_quantity(raw_stock: str | None) -> int | None:
    if not raw_stock:
        return None

    integer_part = str(raw_stock).split(",")[0].split(".")[0]

    try:
        return int(integer_part) if integer_part.isdigit() else None
    except ValueError:
        return None


# WEIGHT NORMALISATION
def normalise_weight(raw_weight: str | None) -> Decimal | None:
    if not raw_weight:
        return None

    cleaned = str(raw_weight).strip().replace(",", ".")

    try:
        weight = Decimal(cleaned)
        if weight == 0:
            return None
        return weight
    except (InvalidOperation, ValueError):
        return None


# CATEGORY NORMALISATION
def normalise_category(raw_category: str | None) -> str | None:
    if not raw_category:
        return None

    category = raw_category.strip().replace("_", " ")
    category = re.sub(r"\s+", " ", category).strip()
    category = re.sub(r"^\d+(?:[\.,]\d+)?[a-zA-Z]*\s+", "", category).strip()

    if len(category) < 3:
        return None

    if re.match(r"^\d+([a-zA-Z]{1,2})?$", category):
        return None

    if re.match(r"^\d+[a-zA-Z]+", category):
        return None

    if not re.match(r"^[\w\s-]+$", category):
        return None

    if category.lower() in ("other", ""):
        return None

    tokens = category.split()
    alpha_tokens = [token for token in tokens if re.fullmatch(r"[A-Za-z]+", token)]

    if alpha_tokens and max(len(token) for token in alpha_tokens) < 3:
        return None

    if any(re.search(r"(?=.*[A-Za-z])(?=.*\d)", token) for token in tokens):
        return None

    return category.title()


def parse_external_condition(description: str | None) -> str | None:
    if not description:
        return None
    match = re.search(
        r"External\s+Condition\s*:\s*([^;]+)",
        description,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip().lower()


# CONDITION PARSING FROM DESCRIPTION
def parse_condition(
    raw_condition: str | None,
    description: str | None
) -> int | None:
    if not raw_condition:
        return None

    condition_compact = re.sub(r"\s+", "", raw_condition.strip().upper())

    if condition_compact == "DEFECTIVE":
        return None

    if condition_compact == "USED":
        return 5

    if condition_compact == "NEW" or condition_compact == "NEWSURPLUS":
        external_condition = parse_external_condition(description)
        if external_condition == "perfect":
            return 2
        return 3

    return None


def row_context(row: dict) -> dict:
    return {
        "reference": row.get("reference") if row.get("reference") is not None else row.get("Part_Number"),
        "manufacturer": row.get("brand") if row.get("brand") is not None else row.get("Brand"),
        "condition": row.get("condition") if row.get("condition") is not None else row.get("Product_condition"),
    }


# DATABASE HELPERS
def fetch_one(cursor, query: str, params: tuple):
    cursor.execute(query, params)
    return cursor.fetchone()


def fetch_brand_id(cursor, brand_name: str) -> int:
    row = fetch_one(
        cursor,
        "SELECT id FROM brands WHERE name = %s",
        (brand_name,),
    )
    if row:
        return row["id"]
    cursor.execute("INSERT INTO brands (name) VALUES (%s)", (brand_name,))
    return cursor.lastrowid


def fetch_category_id(cursor, name: str) -> int:
    row = fetch_one(
        cursor,
        "SELECT id FROM categories WHERE name = %s",
        (name,),
    )
    if row:
        return row["id"]
    cursor.execute(
        "INSERT INTO categories (name) VALUES (%s)",
        (name,),
    )
    return cursor.lastrowid


def fetch_product_by_reference(cursor, reference: str):
    cursor.execute(
        "SELECT id, sku, brand_id, category, weight_kg, gtin FROM products WHERE reference = %s",
        (reference,),
    )
    return cursor.fetchone()


def fetch_product_by_sku(cursor, sku: str):
    cursor.execute(
        "SELECT id, sku, reference, brand_id, category, weight_kg, gtin FROM products WHERE sku = %s",
        (sku,),
    )
    return cursor.fetchone()


def fetch_existing_supplier_price(cursor, reference: str, sku: str, condition_id: int):
    cursor.execute(
        """SELECT pr.id, pr.product_id, pr.price, pr.quantity, p.sku
           FROM prices pr
           JOIN products p ON p.id = pr.product_id
           WHERE pr.supplier_id = %s
             AND pr.condition_id = %s
             AND pr.currency = %s
             AND (p.reference = %s OR p.sku = %s)
           ORDER BY (pr.quantity > 0) DESC, pr.id ASC
           LIMIT 1""",
        (SUPPLIER_ID, condition_id, DEFAULT_CURRENCY, reference, sku),
    )
    return cursor.fetchone()


def insert_product(
    cursor,
    reference: str,
    brand_id: int,
    category_id: int | None,
    weight_kg: Decimal | None,
    gtin: str | None,
    sku: str,
) -> int:
    cursor.execute(
        "INSERT INTO products (reference, brand_id, category, weight_kg, gtin, sku) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (reference, brand_id, category_id, weight_kg, gtin, sku),
    )
    return cursor.lastrowid


def get_next_filename_for_product(cursor, sku: str) -> str:
    cursor.execute(
        "SELECT alt_text FROM images WHERE alt_text LIKE %s",
        (f"{sku}_%",)
    )
    rows = cursor.fetchall()

    max_index = 0
    for row in rows:
        alt_text = row["alt_text"]
        match = re.search(rf"{re.escape(sku)}_(\d+)\.jpg$", alt_text)
        if match:
            index = int(match.group(1))
            max_index = max(max_index, index)

    return f"{sku}_{max_index + 1}.jpg"


def fetch_or_insert_image(cursor, image_url: str, sku: str) -> tuple[int, bool]:
    row = fetch_one(
        cursor,
        "SELECT id FROM images WHERE url = %s",
        (image_url,),
    )
    if row:
        return row["id"], False

    alt_text = get_next_filename_for_product(cursor, sku)

    cursor.execute(
        "INSERT INTO images (url, shopify_url, alt_text) VALUES (%s, %s, %s)",
        (image_url, image_url, alt_text),
    )
    return cursor.lastrowid, True


def link_price_to_image(cursor, price_id: int, image_id: int) -> bool:
    cursor.execute(
        "INSERT IGNORE INTO price_images (price_id, image_id) VALUES (%s, %s)",
        (price_id, image_id),
    )
    return cursor.rowcount > 0


# FETCH DATA FROM CSV
def fetch_products(path: str) -> list[dict]:
    try:
        df = pd.read_csv(path, quotechar='"')
        return df.to_dict(orient="records")
    except FileNotFoundError:
        print(f"Error: CSV file not found at {path}")
        return []
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []


# MAIN PROCESSING
def process_products(products: list[dict]) -> tuple[int, int, int, int, int, int, int, list[dict]]:
    connection, cursor = get_db_connection()
    error_logs = []
    products_inserted = 0
    prices_inserted = 0
    prices_updated = 0
    stock_updated = 0
    images_inserted = 0
    price_images_inserted = 0
    zeroed_out = 0

    try:
        brand_cache: dict[str, int] = {}
        category_cache: dict[str, int] = {}
        processed_price_keys: set[tuple[int, int]] = set()

        # STEP 1: Pre-aggregate quantities and prices by (reference, condition_id)
        aggregated: dict[tuple, dict] = {}

        print("\nAggregating quantities and prices from CSV...")
        for row in tqdm(products, desc="Pre-processing CSV"):
            row = normalise_columns(row)

            raw_brand = row.get("brand")
            if raw_brand:
                normalised_brand = normalise_brand(raw_brand)
                if not normalised_brand:
                    continue

            raw_reference = row.get("reference")
            if not raw_reference:
                error_logs.append({**row_context(row), "error": "Missing or unparseable reference"})
                continue

            reference = clean_reference(raw_reference)
            if not reference:
                error_logs.append({**row_context(row), "error": "Invalid reference"})
                continue

            raw_condition = row.get("condition")
            if not raw_condition:
                error_logs.append({**row_context(row), "error": "Missing condition"})
                continue

            description = row.get("description")
            condition_id = parse_condition(raw_condition, description)
            if condition_id is None:
                error_logs.append({**row_context(row), "error": f"Invalid condition {raw_condition}"})
                continue

            raw_quantity = row.get("quantity")
            quantity = normalise_quantity(raw_quantity)
            if quantity is None or quantity < 0:
                error_logs.append({**row_context(row), "error": "Invalid quantity"})
                continue

            raw_price = row.get("price")
            price = normalise_price(raw_price)
            if price is None or price < Decimal("1"):
                error_logs.append({**row_context(row), "error": "Missing or unparseable price" if price is None else f"Price below minimum: {price}"})
                continue

            key = (reference, condition_id)

            if key in aggregated:
                aggregated[key]["total_quantity"] += quantity
                if price > aggregated[key]["highest_price"]:
                    aggregated[key]["highest_price"] = price
                    aggregated[key]["last_row"] = row
            else:
                aggregated[key] = {
                    "total_quantity": quantity,
                    "highest_price": price,
                    "last_row": row,
                    "condition_id": condition_id
                }

        print(f"Aggregated {len(products)} rows into {len(aggregated)} unique product-condition combinations")

        # STEP 2: Process aggregated data
        for (reference, condition_id), agg_data in tqdm(aggregated.items(), desc="Processing aggregated products"):
            try:
                row = agg_data["last_row"]
                quantity = agg_data["total_quantity"]
                price = agg_data["highest_price"]
                sku = build_sku(reference)

                if not sku:
                    error_logs.append({
                        **row_context(row),
                        "error": "Invalid SKU/reference (unknown)"
                    })
                    continue

                existing_price = fetch_existing_supplier_price(cursor, reference, sku, condition_id)

                product_id = None

                if existing_price:
                    product_id = existing_price["product_id"]
                    if existing_price.get("sku"):
                        sku = existing_price["sku"]

                else:
                    product_row = fetch_product_by_reference(cursor, reference)

                    if product_row:
                        product_id = product_row["id"]
                        if product_row.get("sku"):
                            sku = product_row["sku"]

                    if not product_id:
                        product_row = fetch_product_by_sku(cursor, sku)

                        if product_row:
                            product_id = product_row["id"]
                            if product_row.get("sku"):
                                sku = product_row["sku"]

                    if not product_id:
                        raw_brand = row.get("brand")
                        if not raw_brand:
                            error_logs.append({
                                **row_context(row),
                                "error": "Missing reference and brand"
                            })
                            continue

                        brand_name = normalise_brand(raw_brand)
                        if not brand_name or not brand_name.strip():
                            error_logs.append({
                                **row_context(row),
                                "error": "Missing reference and brand"
                            })
                            continue

                        brand_key = brand_name.strip().lower()
                        if brand_key in brand_cache:
                            brand_id = brand_cache[brand_key]
                        else:
                            try:
                                brand_id = fetch_brand_id(cursor, brand_name)
                                brand_cache[brand_key] = brand_id
                            except Exception as e:
                                error_logs.append({
                                    **row_context(row),
                                    "error": f"Failed to create/fetch brand: {e}"
                                })
                                continue

                        raw_category = row.get("category")
                        category_id = None
                        category_name = normalise_category(raw_category)

                        if category_name:
                            category_key = category_name.lower()

                            if category_key in category_cache:
                                category_id = category_cache[category_key]
                            else:
                                try:
                                    category_id = fetch_category_id(cursor, category_name)
                                    category_cache[category_key] = category_id
                                except Exception as e:
                                    error_logs.append({
                                        **row_context(row),
                                        "error": f"Failed to fetch/insert category '{category_name}': {e}"
                                    })
                                    category_id = None

                        weight_kg = normalise_weight(row.get("weight"))
                        gtin = normalise_gtin(row.get("gtin"))

                        if not isinstance(category_id, int):
                            category_id = None
                        if not isinstance(weight_kg, Decimal):
                            weight_kg = None
                        if not isinstance(gtin, str):
                            gtin = None

                        product_id = insert_product(
                            cursor,
                            reference,
                            brand_id,
                            category_id,
                            weight_kg,
                            gtin,
                            sku,
                        )
                        products_inserted += 1
                        connection.commit()

                if not existing_price:
                    cursor.execute(
                        """SELECT id, price, quantity FROM prices
                        WHERE product_id = %s AND supplier_id = %s AND condition_id = %s AND currency = %s""",
                        (product_id, SUPPLIER_ID, condition_id, DEFAULT_CURRENCY)
                    )
                    existing_price = cursor.fetchone()

                if existing_price:
                    existing_price_val = existing_price["price"]
                    existing_quantity_val = int(existing_price["quantity"])

                    price_changed = existing_price_val != price
                    quantity_changed = existing_quantity_val != quantity

                    if price_changed or quantity_changed:
                        cursor.execute(
                            """UPDATE prices
                            SET price = %s, quantity = %s, warranty = %s, lead_time_id = %s, updated = CURRENT_TIMESTAMP
                            WHERE id = %s""",
                            (price, quantity, DEFAULT_WARRANTY, DEFAULT_LEAD_TIME_ID, existing_price["id"])
                        )
                        if price_changed:
                            prices_updated += 1
                        if quantity_changed:
                            stock_updated += 1

                    price_id = existing_price["id"]
                else:
                    cursor.execute(
                        """INSERT INTO prices (product_id, supplier_id, condition_id,
                        lead_time_id, warranty, price, currency, quantity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (product_id, SUPPLIER_ID, condition_id, DEFAULT_LEAD_TIME_ID, DEFAULT_WARRANTY, price, DEFAULT_CURRENCY, quantity)
                    )
                    prices_inserted += 1
                    price_id = cursor.lastrowid

                processed_price_keys.add((product_id, condition_id))

                image_url = row.get("image_url")
                if image_url and not pd.isna(image_url) and price_id:
                    image_url_str = str(image_url).strip()
                    if image_url_str and image_url_str.lower() not in ('nan', 'none', ''):
                        try:
                            image_id, was_inserted = fetch_or_insert_image(cursor, image_url_str, sku)
                            if was_inserted:
                                images_inserted += 1
                            link_inserted = link_price_to_image(cursor, price_id, image_id)
                            if link_inserted:
                                price_images_inserted += 1
                        except Exception as img_err:
                            error_logs.append({**row_context(row), "error": f"Warning: Could not process image for price {price_id}: {img_err}"})

                connection.commit()

            except Exception as exc:
                connection.rollback()
                error_logs.append({**row_context(row), "error": f"Processing error: {exc}"})

        # STEP 3: Zero out quantities for prices not present in the new stock
        print("\nZeroing out stale prices not found in current stock...")
        cursor.execute(
            """SELECT pr.id, pr.product_id, pr.condition_id
               FROM prices pr
               WHERE pr.supplier_id = %s AND pr.quantity > 0""",
            (SUPPLIER_ID,)
        )
        stale_rows = cursor.fetchall()

        for row in stale_rows:
            key = (row["product_id"], row["condition_id"])
            if key not in processed_price_keys:
                cursor.execute(
                    """UPDATE prices SET quantity = 0, updated = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (row["id"],)
                )
                zeroed_out += 1

        connection.commit()

    finally:
        connection.close()

    return products_inserted, prices_inserted, prices_updated, stock_updated, images_inserted, price_images_inserted, zeroed_out, error_logs


# CSV OUTPUT
def save_csv(rows: list[dict], filename: str):
    if rows:
        folder = os.path.dirname(filename)
        if folder:
            os.makedirs(folder, exist_ok=True)
        pd.DataFrame(rows).to_csv(filename, index=False)


# MAIN (local use only — Lambda entry point is lambda_function.handler)
def main():
    print("=" * 60)
    print("Buy2Sell Product Import Script")
    print("=" * 60)

    if not CSV_FILE:
        print("Error: B2S_STOCK_PATH is not set in .env")
        return

    products = fetch_products(CSV_FILE)
    print(f"Total products fetched: {len(products)}")

    if not products:
        print("No products to process.")
        return

    print("\nProcessing products...")
    products_inserted, prices_inserted, prices_updated, stock_updated, images_inserted, price_images_inserted, zeroed_out, error_logs = process_products(products)

    if error_logs:
        save_csv(error_logs, ERROR_LOGS_FILE)
        print(f"\nError logs saved to: {ERROR_LOGS_FILE}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total products fetched: {len(products)}")
    print(f"Products inserted: {products_inserted}")
    print(f"Prices inserted: {prices_inserted}")
    print(f"Prices updated: {prices_updated}")
    print(f"Stock updated: {stock_updated}")
    print(f"Images inserted: {images_inserted}")
    print(f"Price images inserted: {price_images_inserted}")
    print(f"Prices zeroed out (not in stock): {zeroed_out}")
    print(f"Total errors: {len(error_logs)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
