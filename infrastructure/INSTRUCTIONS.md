# Deployment Instructions

### 22/04/2026

### Terraform Installation

Terraform was installed using the official HashiCorp APT repository in `https://developer.hashicorp.com/terraform/install#linux`. To complete this step, simply follow the instructions relevant to your OS - this project will be based on Linux.

First, download and register HashiCorp's GPG signing key so the system can verify the packages it installs.

```bash
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
```

Then, register HashiCorp's package repository with the system's package manager so it can auto-detect and fetch the correct packages.

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
```

Finally, refresh the package index and install Terraform. To confirm that the installation was successful, run `terraform -v`.

```bash
sudo apt update && sudo apt install terraform
```

---

### AWS CLI

Before continuing, make sure you have a valid AWS account with IAM credentials configured. Do not use the root account to do anything except main admin tasks; instead, create users with specific roles and permissions. For Terraform to be able to create resources on our account, we need to configure AWS CLI with the credentials of an IAM user with programmatic access.

To create one, go to the AWS Console and navigate to **IAM → Users → Create user**. Give the user a role-specific name (i.e. admin-dev), then on the permissions step select **Attach policies directly** and add the user to an already created group (one with `AdministratorAccess`). Once the user is created, open it and go to the **Security credentials** tab, then click **Create access key → Command Line Interface (CLI)** as the use case. At the end of the wizard, copy the **Access Key ID** and **Secret Access Key**; the secret will not be shown again.

Once you have these credentials, set the AWS CLI. 

```bash
aws configure
```

You will be prompted to insert the AWS Access Key ID, Secret Access Key, default region (`eu-central-1`), and output format (simply click *Enter*).

---

### 23/04/2026

### DB Master Password

The database master password cannot be hardcoded in the code and must be provided at deploy time using Terraform variables. This approach was chosen over AWS Secrets Manager to reduce overhead costs.

Create a file named `.terraform.tfvars` inside the `infrastructure/` directory with the following content and add this file to .gitignore. Replace the follwoing placeholder with the actual password:

```hcl
db_master_password = "your-secure-password"
```

** *AWS only accepts hexadecimal passwords*

Terraform will automatically fetch and read the value of this variable when the `-var-file` flag is passed during `apply` (explained the next section).

---

### Deploying the Infrastructure

Run these commands from the `infrastructure/` directory. `init` downloads the required providers, `validate` checks the configuration for syntax errors, `plan` previews what will be created, and `apply` provisions the actual AWS resources.

```bash
cd infrastructure/

terraform init
terraform validate
terraform plan
terraform apply -var-file=.terraform.tfvars
```

** *Every time a new provider is added to the configuration,* `Terraform init` *needs to be ran*

After a successful apply, Terraform will output the Aurora cluster endpoint. If there are any errors during this process, the logs will show what to look for.

---

### Connecting to the Database

AWS RDS requires encrypted connections, that is why we need to download the AWS RDS SSL certificate bundle before continuing. This downloads the official certificate bundle used to verify the server's identity. The file must be present in the `infrastructure/` directory before connecting.

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

To be able to manage PostgreSQL via command-line, `psql` must be installed if it is not already present in the system:

```bash
sudo apt update && sudo apt install postgresql-client
```

Set `RDSHOST` to the Aurora's cluster endpoint. There are two ways to retrieve it: the easiest is to check the Terraform output printed at the end of `terraform apply` — it lists the `cluster_endpoint` value directly. Alternatively, go to the AWS Console, navigate to **RDS → Databases**, select the Aurora cluster, and copy the **Writer endpoint** shown under the Connectivity tab. The `sslmode=verify-full` flag enforces a fully verified encrypted connection using the certificate downloaded above. Once you have that value, run:

```bash
export RDSHOST="<your-cluster-endpoint>"

psql "host=$RDSHOST port=5432 dbname=ebdb user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem"
```

---

### Database Migration

The `db_tools/` directory contains the scripts used to migrate the existing MariaDB database to Aurora PostgreSQL.

**Step 1 — Convert the MariaDB dump to PostgreSQL**

The original data is an .sql file exported from MariaDB. This script rewrites the SQL syntax to make it compatible with PostgreSQL — handling differences in data types, quoting, and engine-specific statements. The output file `postgres_EB.sql` is what gets imported into Aurora.

```bash
python3 db_tools/mysql_dump_to_postgres.py db_tools/preprod_EB_230426.sql db_tools/postgres_EB.sql
```
*If you modify any of the paths, adjust the above command accordingly*

**Step 2 — Import into Aurora**

Once converted, this PostgreSQL file needs to be uploaded to the Aurora database. Make sure `RDSHOST` is still set in the session from the previous step (run `echo $RDSHOST` to verify). The database name `ebdb` is the initial database that Aurora created at provision time — it is defined as the default value of the `db_name` variable in `modules/aws-aurora/variables.tf`. This will populate it with all tables and data from the original MariaDB dump.

```bash
psql -h "$RDSHOST" -U postgres -d ebdb -f db_tools/postgres_EB.sql
```
