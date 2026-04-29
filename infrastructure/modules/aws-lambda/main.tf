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

resource "aws_lambda_function" "this" {
  filename         = data.archive_file.lambda.output_path
  function_name    = "${var.project_name}-hello-world"
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
