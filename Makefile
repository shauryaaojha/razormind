# Thin alias layer. scripts/task.py is the single implementation, and it runs
# every check inside Docker -- nothing is installed on the host.
#
# `make` is not present on every developer machine (Windows especially), so
# these two are interchangeable:
#     make check
#     python scripts/task.py check

TASK := python scripts/task.py

.PHONY: help build up down dev web psql shell lint fmt types boundaries nofloat test check

help:
	@$(TASK) --list

build up down dev web psql shell lint fmt types boundaries nofloat test check:
	@$(TASK) $@
