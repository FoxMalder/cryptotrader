#!/usr/bin/env bash

set -e

DB_URL=$(grep "dsn: postgres" $CONFIG_PATH | cut -d " " -f 2)

exec migrate -path /usr/migrations -database $DB_URL?sslmode=disable "$@"
