# Migrating MariaDB / MySQL dumps to PostgreSQL

This repository provides a workflow to convert **`.sql` files exported from MariaDB or MySQL** (e.g. with phpMyAdmin or `mysqldump`) into a **PostgreSQL**-compatible script.

## Files involved

| File | Role |
|------|------|
| `preprod_EB_080426.sql` | Source dump in MariaDB/MySQL dialect (`ENGINE=InnoDB`, backticks, multiline `INSERT`, etc.). |
| `db_tools/mysql_dump_to_postgres.py` | Tool that reads the MySQL dump and emits PostgreSQL SQL (streaming; suitable for large dumps). |
| `postgres_EB.sql` | **Generated output**: `preprod_eb` schema, data, indexes, and constraints in PostgreSQL. Do not edit by hand; regenerate with the script. |

You can choose a different output filename when running the converter (e.g. another `*_EB.sql`).

## Requirements

- **Python 3.8+** (standard library only; no `pip install`).
- Disk space: the output is usually **on the same order of magnitude** as the source dump (hundreds of MB or more).
- To **import** the result: `psql`, or a Docker container using the `postgres` image.

## Steps

### 1. Generate PostgreSQL SQL

From the repository root:

```bash
python3 db_tools/mysql_dump_to_postgres.py db_tools/preprod_EB_230426.sql db_tools/postgres_EB.sql
```

For another MySQL/MariaDB dump:

```bash
python3 db_tools/mysql_dump_to_postgres.py /path/to/mysql_dump.sql /path/to/output/postgres.sql
```

The script:

- Skips headers and MySQL-specific `ALTER` sections from the original dump.
- Emits DDL in the **`preprod_eb`** schema, with type mapping (e.g. `longtext` → `text`, `decimal` → `numeric`).
- Rewrites string literals (e.g. MySQL `\'` escaping → PostgreSQL doubled single quotes).
- Handles the typical phpMyAdmin **multiline `INSERT`** block (`INSERT ... VALUES` header and rows on the following lines).

### 2. Import into PostgreSQL

With `psql`:

```bash
psql "postgresql://USER:PASSWORD@HOST:5432/DATABASE" \
  -v ON_ERROR_STOP=1 \
  -f postgres_EB.sql
```

With Docker (example: mount the file and run inside the container):

```bash
docker run -d --name pg-migrate -e POSTGRES_PASSWORD=postgres -p 54333:5432 \
  -v "$PWD/postgres_EB.sql:/tmp/dump.sql:ro" postgres:16

# Wait for startup, then load
docker exec pg-migrate pg_isready -U postgres
docker exec pg-migrate psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f /tmp/dump.sql
```

After a successful import, data lives in the **`preprod_eb`** schema (not `public`).

### 3. Typical connection

```text
host=… port=5432 dbname=… user=… password=…
options=-csearch_path=preprod_eb,public
```

Or in session:

```sql
SET search_path TO preprod_eb, public;
```

## Limitations and notes

- The converter targets the **format** used in this project (structure similar to the reference dump). Other dumps (different ordering, `LOAD DATA`, procedures, views, etc.) may need changes in `db_tools/mysql_dump_to_postgres.py`.
- **Types and semantics**: MySQL `AUTO_INCREMENT` becomes `bigint` with explicit inserted values; the “next id” is not configured automatically unless you add sequences or `IDENTITY` afterwards.
- The output file is **large**; it is often excluded from Git or stored with **Git LFS**.

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Empty or nearly empty import | The MySQL dump must use multiline `INSERT`; the script groups lines until one ends with `;`. |
| PostgreSQL syntax error | PostgreSQL version (14+ recommended) and ensure the final `.sql` is not mixed with MySQL fragments. |
| TLS failure on `docker pull` | Use an already pulled `postgres` image, or fix proxy/certificates for Docker. |

For new dumps, always repeat **step 1** and re-test the import before promoting to production.
