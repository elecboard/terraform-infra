data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "rds_sg" {
  name        = "${var.project_name}-rds-sg"
  description = "Security group for Aurora PostgreSQL Serverless"

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "PostgreSQL access"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}

resource "aws_db_subnet_group" "rds" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name = "${var.project_name}-db-subnet-group"
  }
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier     = "${var.project_name}-aurora-cluster"
  engine                 = "aurora-postgresql"
  engine_version         = "17"
  database_name          = var.db_name
  master_username        = var.db_master_username
  master_password        = var.db_master_password
  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  skip_final_snapshot    = true
  storage_encrypted      = true
  apply_immediately      = true

  serverlessv2_scaling_configuration {
    max_capacity = var.rds_max_capacity
    min_capacity = var.rds_min_capacity
  }

  tags = {
    Name = "${var.project_name}-aurora-cluster"
  }
}

resource "aws_rds_cluster_instance" "aurora" {
  cluster_identifier           = aws_rds_cluster.aurora.id
  instance_class               = "db.serverless"
  engine                       = aws_rds_cluster.aurora.engine
  engine_version               = aws_rds_cluster.aurora.engine_version
  publicly_accessible          = true
  performance_insights_enabled = false

  tags = {
    Name = "${var.project_name}-aurora-instance"
  }
}
