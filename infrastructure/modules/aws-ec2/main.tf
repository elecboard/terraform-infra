data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Latest Amazon Linux 2023 AMI (x86_64). SSM agent is preinstalled, so the host
# is reachable by Run Command with no SSH and no inbound ports.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# AWS-managed KMS key behind SSM SecureString — the host decrypts the .env with it.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

locals {
  account_id       = data.aws_caller_identity.current.account_id
  app_dir          = "/opt/${var.service_name}"
  ecr_arn          = "arn:aws:ecr:${var.region}:${local.account_id}:repository/${var.ecr_repository_name}"
  dotenv_param_arn = "arn:aws:ssm:${var.region}:${local.account_id}:parameter${var.dotenv_param_name}"
}

# --- Network: egress-only. Reaches Aurora, Shopify, ECR and SSM outbound.
# No inbound — deploys arrive via SSM Run Command; Bull Board via SSM port-forward.
resource "aws_security_group" "host" {
  name        = "${var.service_name}-ec2-sg"
  description = "Egress-only SG for the ${var.service_name} Docker host"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound (Aurora, Shopify, ECR, SSM)"
  }

  tags = {
    Name = "${var.service_name}-ec2-sg"
  }
}

# --- IAM: the host's identity. Pulls from ECR, registers with SSM, reads .env.
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "${var.service_name}-ec2"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# SSM agent registration + Run Command (how deploys reach the host).
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "host" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.ecr_arn]
  }

  statement {
    sid       = "ReadDotenv"
    actions   = ["ssm:GetParameter"]
    resources = [local.dotenv_param_arn]
  }

  statement {
    sid       = "DecryptDotenv"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }
}

resource "aws_iam_role_policy" "host" {
  name   = "${var.service_name}-ec2"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name = "${var.service_name}-ec2"
  role = aws_iam_role.host.name
}

# --- The host itself ---
resource "aws_instance" "host" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = element(tolist(data.aws_subnets.default.ids), 0)
  vpc_security_group_ids      = [aws_security_group.host.id]
  iam_instance_profile        = aws_iam_instance_profile.host.name
  associate_public_ip_address = true

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }

  user_data = templatefile("${path.module}/files/user-data.sh.tftpl", {
    region       = var.region
    dotenv_param = var.dotenv_param_name
    app_dir      = local.app_dir
    compose_yaml = file("${path.module}/files/docker-compose.prod.yml")
  })

  # Rebuild the host if the bootstrap or compose definition changes.
  user_data_replace_on_change = true

  tags = {
    Name = var.service_name
  }
}
