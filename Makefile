dc=docker-compose
MIGRATE=$(dc) run --rm migrate

ARGS=

NPROC=$(shell python -c 'import multiprocessing as m; print(m.cpu_count())')


# <--- Help section

# @todo #500:60m Renew or rm Makefile help section.
#  Create discussion to choose one of "renew" or "rm".

define MAKE_HELP=
Commands list:
- Apply up either all migrations, or all before the specified migration
>>> make migrate-up
>>> make MIGRATE_TO=1 migrate-up

- Apply down either all migrations, or all before the specified migration
>>> make migrate-down
>>> make MIGRATE_TO=1 migrate-down

- Set version MIGRATE_TO but don't run migration
>>> make migrate-force
>>> make MIGRATE_TO=1 migrate-force

- Print current migration version
>>> make migrate-version

- Print usage
>>> make migrate-help
endef

# `export` makes the variable as a string
export MAKE_HELP
help:
	@echo "$$MAKE_HELP"

# --->

# <--- Dev section ---

test:
	$(dc) run --rm bot pytest $(ARGS)

test-parallel:
	$(dc) run --rm bot pytest -n $(NPROC) $(ARGS)

test-combat:
	$(dc) run --rm bot pytest --runcombat -s $(ARGS)

coala:
	$(dc) run --rm coala $(ARGS)

coala-ci:
	$(dc) run --rm coala bash -c "source /coala_env/bin/activate && coala --ci"

mypy:
	$(dc) run --rm mypy $(ARGS)

pdd-lint:
	$(dc) run --rm pdd-lint $(ARGS)

# Hint: you can use it in parallel
# >>> make -j lint
lint: coala-ci mypy pdd-lint

lint-n-push: clean
	@$(MAKE) -j lint
	git push origin `git rev-parse --abbrev-ref HEAD`

# --->


# <--- App section ---

clean:
	rm -f `find . -name *.orig`
run: bot-run
upd: bot-upd panel-upd
stop: bot-stop panel-stop
# stop all services, not only bot and panel
stop-all:
	$(dc) stop

# miss "up" rule, because bot-up and panel-up are both forever rules
# miss "logs" rule, because mixed log from two apps is not informative

# --->


# <--- Bot section ---

bot-run:
	$(dc) run --rm bot

bot-up:
	$(dc) up bot

bot-upd:
	$(dc) up -d bot

bot-logs:
	$(dc) logs bot

bot-stop:
	$(dc) stop bot

# --->

# <--- Cli section ---
# useful commands for bot administration

cli-reverse-length:
	$(dc) exec db bash -c "psql -Ucryptotrader <<< 'select count(*) from order_pairs;'"

# --->

# <--- Panel section ---

panel-build:
	$(dc) run --rm panel-js

panel-up:
	$(dc) up panel

panel-upd:
	$(dc) up -d panel

# no panel-run, because docker run does not share ports to host

panel-logs:
	$(dc) logs panel

panel-stop:
	$(dc) stop panel

# --->


# <--- Migrate section
migrate-up:
	$(MIGRATE) up $(MIGRATE_TO)

migrate-down:
	$(MIGRATE) down $(MIGRATE_TO)

migrate-force:
	$(MIGRATE) force $(MIGRATE_TO)

migrate-version:
	$(MIGRATE) version

migrate-help:
	$(MIGRATE) -help

# --->
