import os
import json
import boto3

s3_client = boto3.client("s3")


def handler(event, context):
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    lines = content.splitlines()

    print(f"File uploaded: s3://{bucket}/{key}")
    print("--- First 5 lines ---")
    for i, line in enumerate(lines[:5]):
        print(f"  {i + 1}: {line}")
    print("---------------------")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Hello, World!",
            "file": key,
            "lines_previewed": min(5, len(lines)),
        }),
    }
