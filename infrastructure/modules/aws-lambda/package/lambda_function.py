import os
import json
import boto3

from buy2sell_filter import fetch_products, process_products, save_csv, ERROR_LOGS_FILE

s3_client = boto3.client("s3")


def handler(event, context):
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    local_path = "/tmp/Stocklist.csv"
    print(f"Downloading s3://{bucket}/{key} to {local_path}")
    s3_client.download_file(bucket, key, local_path)

    products = fetch_products(local_path)
    print(f"Total products fetched: {len(products)}")

    if not products:
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "No products to process"}),
        }

    (products_inserted, prices_inserted, prices_updated,
     stock_updated, images_inserted, price_images_inserted,
     zeroed_out, error_logs) = process_products(products)

    if error_logs:
        save_csv(error_logs, ERROR_LOGS_FILE)
        error_key = f"buy2sell/logs/{os.path.basename(ERROR_LOGS_FILE)}"
        s3_client.upload_file(ERROR_LOGS_FILE, bucket, error_key)
        print(f"Error logs uploaded to s3://{bucket}/{error_key}")

    summary = {
        "products_fetched": len(products),
        "products_inserted": products_inserted,
        "prices_inserted": prices_inserted,
        "prices_updated": prices_updated,
        "stock_updated": stock_updated,
        "images_inserted": images_inserted,
        "price_images_inserted": price_images_inserted,
        "zeroed_out": zeroed_out,
        "total_errors": len(error_logs),
    }

    print("SUMMARY:", json.dumps(summary, indent=2))

    return {"statusCode": 200, "body": json.dumps(summary)}
