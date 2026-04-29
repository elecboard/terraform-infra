import os
import json


def handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Hello, World!",
            "db_host":   os.environ.get("DB_HOST"),
            "db_name":   os.environ.get("DB_NAME"),
            "db_schema": os.environ.get("DB_SCHEMA"),
            "db_user":   os.environ.get("DB_USER"),
        }),
    }
