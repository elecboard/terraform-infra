data "archive_file" "lambda" {
  type        = "zip"
  source_file = "${path.module}/lambda/lambda_function.py"
  output_path = "${path.module}/lambda/lambda_function.zip"
}

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"

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

resource "aws_iam_role_policy" "s3_read" {
  name = "${var.project_name}-lambda-s3-read"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:GetObject"
      Resource = "${var.s3_bucket_arn}/${var.s3_trigger_prefix}*"
    }]
  })
}

resource "aws_lambda_function" "this" {
  filename         = data.archive_file.lambda.output_path
  function_name    = "${var.project_name}-aws-lambda-b2s"
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler"
  source_code_hash = data.archive_file.lambda.output_base64sha256
  runtime          = "python3.12"

  environment {
    variables = {
      DB_USER     = var.db_user
      DB_PASSWORD = var.db_password
      DB_HOST     = var.db_host
      DB_NAME     = var.db_name
      DB_SCHEMA   = var.db_schema
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

resource "aws_s3_bucket_notification" "lambda_trigger" {
  bucket = var.s3_bucket_id

  lambda_function {
    lambda_function_arn = aws_lambda_function.this.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = var.s3_trigger_prefix
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}
