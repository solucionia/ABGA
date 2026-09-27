# Un solo punto de entrada para el trabajo del día a día.
#
#   make            ayuda
#   make instalar   dependencias de desarrollo en .venv
#   make pruebas    toda la suite (se omite lo que necesita los datos reales si no están)
#   make rapido     sólo lo que no depende de fixtures (lo que corre la CI)
#   make reales     lo que sí depende de los fixtures del ERP
#   make lint       ruff
#   make tipos      mypy
#   make verificar  lint + tipos + pruebas
#
# Ningún objetivo de este Makefile llama al ERP ni gasta tokens: eso sólo pasa con
# `backend/scripts/precalentar.py` y con los workflows de n8n, y va con permiso explícito.

PY ?= ./.venv/bin/python
VENV ?= .venv

.DEFAULT_GOAL := ayuda

ayuda:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t 14

instalar: $(VENV)/bin/python  ## Instala las dependencias de desarrollo
	$(PY) -m pip install -q -r backend/requirements-dev.txt
	@echo "listo: make pruebas"

$(VENV)/bin/python:
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install -q --upgrade pip

pruebas:  ## Toda la suite (omite los datos reales si no están)
	$(PY) -m pytest

rapido:  ## Sólo lo que no necesita fixtures: es lo que corre la CI
	$(PY) -m pytest -m "not datos_reales and not lento"

reales:  ## Sólo lo que usa los fixtures reales del ERP
	$(PY) -m pytest -m "datos_reales and not lento"

lento:  ## Los verificadores heredados, completos (minutos)
	$(PY) -m pytest -m lento

migrar:  ## Pone al día el esquema de la base (migraciones versionadas de alembic)
	$(PY) backend/scripts/migrar.py

cobertura:  ## Suite rápida con informe de cobertura del dominio
	$(PY) -m pytest -m "not lento" --cov=app --cov-report=term-missing

lint:  ## Estilo y errores lógicos (ruff)
	$(PY) -m ruff check backend/app backend/tests backend/scripts

lint-fix:  ## Aplica los arreglos de estilo automáticos de ruff
	$(PY) -m ruff check --fix backend/app backend/tests backend/scripts

tipos:  ## Comprobación de tipos (mypy)
	$(PY) -m mypy

verificar: lint tipos pruebas  ## Lo que hay que tener en verde antes de dar algo por hecho
	@echo "todo en verde"

.PHONY: ayuda instalar pruebas rapido reales lento migrar cobertura lint lint-fix tipos verificar
