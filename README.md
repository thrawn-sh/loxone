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
$> poetry run ./loxone/download_miniserver.py --server="<MINISERVER>" --user="<LOXONE_USER>" --password="<LOXONE_PASSWORD>" --output="<LOXONE_CONFIGURATION>"
$> poetry run ./loxone/monitor.py --server="<MINISERVER>" --user="<LOXONE_USER>" --password="<LOXONE_PASSWORD>"  --db-uri="postgresql://<USER>:<PASSWORD>@<DB_HOST>/<DATABASE>"
```

### Export the available statistics from Loxone to PostgreSQL
```sh
# create database and user
$> sudo --user=postgres createuser --no-createdb --no-createrole --no-superuser --pwprompt <USER>
$> sudo --user=postgres createdb --encoding=UTF-8 --owner=<USER> <DATABASE>

# create schema for database
$> cat loxone.sql | psql --host=<HOST> --dbname=<DATABASE> <USER>
```

## Build docker container
```sh
# ensure everything is commited
$> docker build --tag shadowhunt/loxone:latest --tag shadowhunt/loxone:$(git log -1 --format="%at") .
$> docker push shadowhunt/loxone:$(git log -1 --format="%at")
$> docker push shadowhunt/loxone:latest
```
