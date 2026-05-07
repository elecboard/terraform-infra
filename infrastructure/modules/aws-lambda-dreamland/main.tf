resource "null_resource" "lambda_build" {
  triggers = {
    requirements = filemd5("${path.module}/requirements.txt")
    handler      = filemd5("${path.module}/package/lambda_function.py")
    filter       = filemd5("${path.module}/package/dreamland_filter.py")
    db_conn      = filemd5("${path.module}/package/config/db_connection.py")
  }

  provisioner "local-exec" {
    command = <<-EOT
      mkdir -p ${path.module}/build
      pip install -r ${path.module}/requirements.txt \
        -t ${path.module}/build \
        --upgrade --quiet \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 312 \
        --only-binary=:all:
      cp -r ${path.module}/package/. ${path.module}/build/
    EOT
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/build"
  output_path = "${path.module}/lambda_function.zip"

  depends_on = [null_resource.lambda_build]
}

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-dreamland-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "s3_access" {
  name = "${var.project_name}-dreamland-lambda-s3-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "s3:GetObject"
        Resource = [
          "${var.s3_bucket_arn}/${var.s3_trigger_prefix}*",
          "${var.s3_bucket_arn}/lambda/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = [
          "${var.s3_bucket_arn}/dreamland/logs/*",
          "${var.s3_bucket_arn}/images/*",
        ]
      },
    ]
  })
}

resource "aws_s3_object" "lambda_zip" {
  bucket = var.s3_bucket_id
  key    = "lambda/aws-lambda-dreamland.zip"
  source = data.archive_file.lambda.output_path
  etag   = data.archive_file.lambda.output_md5
}

resource "aws_lambda_function" "this" {
  s3_bucket        = aws_s3_object.lambda_zip.bucket
  s3_key           = aws_s3_object.lambda_zip.key
  function_name    = "${var.project_name}-aws-lambda-dreamland"
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler"
  source_code_hash = data.archive_file.lambda.output_base64sha256
  runtime          = "python3.12"
  timeout          = 900
  memory_size      = 512

  environment {
    variables = {
      DB_USER          = var.db_user
      DB_PASSWORD      = var.db_password
      DB_HOST          = var.db_host
      DB_NAME          = var.db_name
      DB_SCHEMA        = var.db_schema
      IMAGES_URL       = var.images_url
      BASE_URL         = var.base_url
      IMAGES_S3_BUCKET = var.s3_bucket_id
    }
  }

  tags = {
    Project = var.project_name
  }
}

resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.s3_bucket_arn
}
