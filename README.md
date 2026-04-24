# AWS Aurora Infrastructure with Terraform

This project uses Terraform to provision an AWS Aurora PostgreSQL database along with the supporting AWS infrastructure. It includes an S3 bucket for receiving raw data and AWS Lambda functions that are triggered when new files are uploaded. The Lambda layer is responsible for initiating the processing scripts in response to those events.

---

## Project Structure

```
infrastructure/
├── main.tf                    # Root module — providers and module calls
├── variables.tf               # Root-level input variables
├── terraform.tf               # Provider version constraints
├── global-bundle.pem          # AWS RDS SSL certificate bundle
├── modules/
│   ├── aws-aurora/
│   │   ├── main.tf            # Security group, subnet group, RDS cluster and instance
│   │   ├── variables.tf       # Input variables for the Aurora module
│   │   └── outputs.tf         # Cluster endpoint and identifier outputs
│   └── aws-ec2-instance/
│       ├── main.tf            # EC2 instance resource
│       └── variables.tf       # Input variables for the EC2 module
db_tools/
├── mysql_dump_to_postgres.py  # Converts a MySQL dump to PostgreSQL-compatible SQL
├── preprod_EB_230426.sql      # Original MySQL dump
└── postgres_EB.sql            # Converted PostgreSQL dump (ready to import)
```

### `infrastructure/`

Contains all Terraform configuration files that define and provision the AWS infrastructure. It is organised into reusable modules under `modules/`, each responsible for a specific AWS resource group — the Aurora PostgreSQL database cluster and the EC2 instance. The root-level files wire the modules together, declare the required providers, and expose the input variables used at deploy time.

### `db_tools/`

Contains the one-time migration tooling used to transition the existing relational data from MariaDB to Aurora PostgreSQL. The Python script handles the syntax conversion between the two engines, and the SQL files represent the migration at each stage — the original MariaDB .sql export and the converted PostgreSQL dump ready to be imported into the provisioned database.
