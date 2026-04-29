resource "aws_s3_bucket" "this" {
  bucket = "${var.project_name}-${var.bucket_suffix}"

  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = var.versioning_enabled ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_object" "buy2sell" {
  bucket = aws_s3_bucket.this.id
  key    = "buy2sell/"
}

resource "aws_s3_object" "maxodeals" {
  bucket = aws_s3_bucket.this.id
  key    = "maxodeals/"
}
