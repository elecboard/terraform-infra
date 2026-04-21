#!/usr/bin/env python3
"""
Stream-convert a phpMyAdmin MySQL/MariaDB dump to PostgreSQL-compatible SQL.

  python3 tools/mysql_dump_to_postgres.py preprod_EB_080426.sql postgres_EB.sql
"""

from __future__ import annotations

import argparse
import re

PG_HEADER = """-- Converted from MySQL/MariaDB dump for PostgreSQL
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;

BEGIN;

SELECT pg_catalog.set_config('session_replication_role', 'replica', true);

"""

PG_FOOTER = """
ANALYZE preprod_eb.brands;
ANALYZE preprod_eb.brand_images;
ANALYZE preprod_eb.categories;
ANALYZE preprod_eb.conditions;
ANALYZE preprod_eb.images;
ANALYZE preprod_eb.lead_times;
ANALYZE preprod_eb.prices;
ANALYZE preprod_eb.price_images;
ANALYZE preprod_eb.products;
ANALYZE preprod_eb.product_images;
ANALYZE preprod_eb.suppliers;

SELECT pg_catalog.set_config('session_replication_role', 'origin', true);

COMMIT;
"""

DDL_BLOCK = r"""
CREATE SCHEMA IF NOT EXISTS preprod_eb;
SET search_path TO preprod_eb, public;

DROP TABLE IF EXISTS price_images CASCADE;
DROP TABLE IF EXISTS product_images CASCADE;
DROP TABLE IF EXISTS prices CASCADE;
DROP TABLE IF EXISTS brand_images CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS images CASCADE;
DROP TABLE IF EXISTS lead_times CASCADE;
DROP TABLE IF EXISTS conditions CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS brands CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;

CREATE TABLE brands (
  id bigint PRIMARY KEY,
  name character varying(255) NOT NULL
);

CREATE TABLE categories (
  id bigint PRIMARY KEY,
  name character varying(255) NOT NULL
);

CREATE TABLE conditions (
  id bigint PRIMARY KEY,
  name character varying(100) NOT NULL
);

CREATE TABLE suppliers (
  id bigint PRIMARY KEY,
  name character varying(255) NOT NULL
);

CREATE TABLE images (
  id bigint PRIMARY KEY,
  shopify_url text,
  url text NOT NULL,
  alt_text character varying(255)
);

CREATE TABLE lead_times (
  id bigint PRIMARY KEY,
  name character varying(100) NOT NULL
);

CREATE TABLE products (
  id bigint PRIMARY KEY,
  sku character varying(255) NOT NULL,
  reference character varying(255) NOT NULL,
  weight_kg numeric(8, 2),
  hs_code character varying(255),
  gtin character(14),
  brand_id bigint NOT NULL,
  shopify_handle character varying(255),
  description text,
  ai_description text,
  category bigint,
  sub_category bigint,
  sub_sub_category bigint
);

CREATE TABLE brand_images (
  id bigint PRIMARY KEY,
  brand_id bigint NOT NULL,
  shopify_url text,
  url text NOT NULL,
  alt_text character varying(255)
);

CREATE TABLE prices (
  id bigint PRIMARY KEY,
  product_id bigint NOT NULL,
  supplier_id bigint NOT NULL,
  condition_id bigint NOT NULL,
  supplier_item_id character varying(255),
  price numeric(10, 2) NOT NULL,
  currency character(3) NOT NULL,
  quantity bigint NOT NULL DEFAULT 0,
  lead_time_id bigint,
  warranty smallint,
  updated timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION preprod_eb.prices_set_updated()
RETURNS trigger AS $$
BEGIN
  NEW.updated := CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prices_set_updated
  BEFORE UPDATE ON prices
  FOR EACH ROW
  EXECUTE FUNCTION preprod_eb.prices_set_updated();

CREATE TABLE price_images (
  price_id bigint NOT NULL,
  image_id bigint NOT NULL,
  PRIMARY KEY (price_id, image_id)
);

CREATE TABLE product_images (
  product_id bigint NOT NULL,
  image_id bigint NOT NULL,
  PRIMARY KEY (product_id, image_id)
);

CREATE UNIQUE INDEX uk_brands_name ON brands (name);
CREATE UNIQUE INDEX uk_categories_name ON categories (name);
CREATE UNIQUE INDEX uk_conditions_name ON conditions (name);
CREATE UNIQUE INDEX uk_suppliers_name ON suppliers (name);

CREATE UNIQUE INDEX uk_brand_images_url_prefix ON brand_images ((substring(url FROM 1 FOR 255)));
CREATE UNIQUE INDEX uk_brand_images_shopify_url_prefix ON brand_images ((substring(shopify_url FROM 1 FOR 255)))
  WHERE shopify_url IS NOT NULL;
CREATE INDEX idx_brand_images_brand ON brand_images (brand_id);

CREATE UNIQUE INDEX uk_images_url_prefix ON images ((substring(url FROM 1 FOR 255)));
CREATE UNIQUE INDEX uk_images_shopify_url ON images (shopify_url) WHERE shopify_url IS NOT NULL;

CREATE UNIQUE INDEX uk_lead_times_name ON lead_times (name);

CREATE UNIQUE INDEX uk_prices_offer ON prices (product_id, supplier_id, condition_id, currency);
CREATE INDEX idx_prices_product ON prices (product_id);
CREATE INDEX idx_prices_supplier ON prices (supplier_id);
CREATE INDEX idx_prices_condition ON prices (condition_id);
CREATE INDEX idx_prices_lead_time ON prices (lead_time_id);

CREATE UNIQUE INDEX uk_products_sku ON products (sku);
CREATE UNIQUE INDEX uk_products_reference ON products (reference);
CREATE UNIQUE INDEX uk_products_shopify_handle ON products (shopify_handle) WHERE shopify_handle IS NOT NULL;
CREATE INDEX idx_products_brand ON products (brand_id);
CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_sub_category ON products (sub_category);
CREATE INDEX idx_products_sub_sub_category ON products (sub_sub_category);

CREATE INDEX idx_price_images_image ON price_images (image_id);
CREATE INDEX idx_product_images_image ON product_images (image_id);

ALTER TABLE ONLY brand_images
  ADD CONSTRAINT fk_brand_images_brand FOREIGN KEY (brand_id) REFERENCES brands (id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE ONLY prices
  ADD CONSTRAINT fk_lead_time FOREIGN KEY (lead_time_id) REFERENCES lead_times (id),
  ADD CONSTRAINT fk_prices_condition FOREIGN KEY (condition_id) REFERENCES conditions (id) ON UPDATE CASCADE,
  ADD CONSTRAINT fk_prices_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT fk_prices_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON UPDATE CASCADE;

ALTER TABLE ONLY price_images
  ADD CONSTRAINT fk_price_images_image FOREIGN KEY (image_id) REFERENCES images (id) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT fk_price_images_price FOREIGN KEY (price_id) REFERENCES prices (id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE ONLY products
  ADD CONSTRAINT fk_products_brand FOREIGN KEY (brand_id) REFERENCES brands (id) ON UPDATE CASCADE,
  ADD CONSTRAINT fk_products_category FOREIGN KEY (category) REFERENCES categories (id) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT fk_products_sub_category FOREIGN KEY (sub_category) REFERENCES categories (id) ON DELETE SET NULL ON UPDATE CASCADE,
  ADD CONSTRAINT fk_products_sub_sub_category FOREIGN KEY (sub_sub_category) REFERENCES categories (id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE ONLY product_images
  ADD CONSTRAINT fk_pi_image FOREIGN KEY (image_id) REFERENCES images (id) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT fk_pi_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE ON UPDATE CASCADE;

"""


def parse_mysql_quoted_string(s: str, start: int) -> tuple[str, int]:
    """s[start] is opening single quote. Returns decoded text and index after closing quote."""
    if start >= len(s) or s[start] != "'":
        raise ValueError("expected opening quote")
    i = start + 1
    out: list[str] = []
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 >= n:
                out.append("\\")
                break
            nxt = s[i + 1]
            if nxt == "'":
                out.append("'")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "b":
                out.append("\b")
            elif nxt == "Z":
                out.append("\x1a")
            elif nxt == "0":
                out.append("\x00")
            else:
                out.append(nxt)
            i += 2
            continue
        if c == "'":
            if i + 1 < n and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ValueError("unterminated MySQL string literal")


def pg_quote_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def convert_row_tuple(inner: str) -> str:
    """Convert comma-separated values inside outer ( ) from MySQL to PostgreSQL."""
    parts: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i] in " \t\r":
            i += 1
        if i >= n:
            break
        if inner.startswith("NULL", i) and (i + 4 >= n or inner[i + 4] in ", \t\r"):
            parts.append("NULL")
            i += 4
        elif inner[i] == "'":
            decoded, j = parse_mysql_quoted_string(inner, i)
            parts.append(pg_quote_literal(decoded))
            i = j
        else:
            j = i
            while j < n and inner[j] != ",":
                j += 1
            parts.append(inner[i:j].strip())
            i = j
        while i < n and inner[i] in " \t\r":
            i += 1
        if i < n and inner[i] == ",":
            i += 1
    return "(" + ", ".join(parts) + ")"


INSERT_RE = re.compile(
    r"^INSERT INTO `(?P<table>[^`]+)`\s*\((?P<cols>[^)]+)\)\s*VALUES\s*(?P<sameline>.*)$",
    re.I,
)


def strip_backticks(ident_list: str) -> str:
    return ident_list.replace("`", "")


def split_mysql_row_tuples(rows_blob: str) -> list[str]:
    """
    Split (..),(..),... into list of '(...)' segments. Parentheses inside
    quoted strings must not affect nesting.
    """
    blob = rows_blob.strip()
    if blob.endswith(";"):
        blob = blob[:-1].strip()
    rows: list[str] = []
    i = 0
    n = len(blob)
    depth = 0
    start = 0
    in_str = False
    bs = False
    while i < n:
        ch = blob[i]
        if bs:
            bs = False
            i += 1
            continue
        if in_str:
            if ch == "\\":
                bs = True
            elif ch == "'":
                if i + 1 < n and blob[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                rows.append(blob[start : i + 1])
            i += 1
            continue
        i += 1
    return rows


def convert_insert_block(block: str, emit) -> None:
    """block is full INSERT ... VALUES ... (possibly multiline) ending with ';' ."""
    stripped = block.strip()
    parts = stripped.split("\n", 1)
    line0 = parts[0]
    tail = parts[1] if len(parts) > 1 else ""
    m = INSERT_RE.match(line0)
    if not m:
        return
    table = m.group("table")
    cols = strip_backticks(m.group("cols"))
    emit(f"INSERT INTO preprod_eb.{table} ({cols}) VALUES\n")
    sameline = (m.group("sameline") or "").strip()
    rows_raw = (sameline + "\n" + tail).strip() if tail else sameline
    segs = split_mysql_row_tuples(rows_raw)
    rows = []
    for seg in segs:
        inner = seg[1:-1]
        rows.append(convert_row_tuple(inner))
    if not rows:
        emit(";\n")
        return
    for k, row in enumerate(rows):
        suffix = "," if k < len(rows) - 1 else ";"
        emit(row + suffix + "\n")


def run_convert(path_in: str, path_out: str) -> None:
    with open(path_in, "r", encoding="utf-8", errors="replace") as inf, open(
        path_out, "w", encoding="utf-8"
    ) as outf:
        outf.write(PG_HEADER)
        outf.write(DDL_BLOCK)
        outf.write("\n")
        buf: list[str] = []
        in_insert = False
        for raw in inf:
            line = raw.rstrip("\n\r")
            if not in_insert:
                if raw.startswith("INSERT INTO `"):
                    in_insert = True
                    buf = [line]
                    if line.rstrip().endswith(";"):
                        convert_insert_block("\n".join(buf), outf.write)
                        in_insert = False
                        buf = []
                continue
            buf.append(line)
            if line.rstrip().endswith(";"):
                convert_insert_block("\n".join(buf), outf.write)
                in_insert = False
                buf = []
        outf.write(PG_FOOTER)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_sql")
    ap.add_argument("output_sql")
    args = ap.parse_args()
    run_convert(args.input_sql, args.output_sql)


if __name__ == "__main__":
    main()
