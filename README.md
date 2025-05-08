# Loxone
python module to interact and read statistics from [Loxone](https://www.loxone.com/) Miniserver.

## Install depencies
```sh
$> poetry install
```

## Check source code
```sh
$> poetry run flake8
```

## Build package
```sh
$> poetry build
```

## Build package
```sh
# automatically pull minor updates
$> poetry update
# list all major updates
$> poetry show --latest --outdated --top-level
```

### Extract mapping part for config into ini file
```sh
$> ./bin/download_miniserver --server="<MINISERVER>" --user="<LOXONE_USER>" --password="<LOXONE_PASSWORD>" --output="<LOXONE_CONFIGURATION>"
$> ./bin/generate_config --configuration="<LOXONE_CONFIGURATION>"
```

### Export the available statistics from Loxone to PostgreSQL
```sh
# create database and user
$> sudo --user=postgres createuser --no-createdb --no-createrole --no-superuser --pwprompt <USER>
$> sudo --user=postgres createdb --encoding=UTF-8 --owner=<USER> <DATABASE>

# create schema for database
$> cat loxone.sql | psql --host=<HOST> --dbname=<DATABASE> <USER>

# create database connection configuration
$> cat > database.ini <<EOF
[postgresql]
host=<HOST>
port=5432
dbname=<DATABASE>
user=<USER>
password=<PASSWORD>
sslmode=require
EOF

$> ./bin/export_postgresql
```
