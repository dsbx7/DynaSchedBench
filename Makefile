.PHONY: help install test docs build check clean

PYTHON ?= python

help:
	@echo "DynaSchedBench developer commands"
	@echo ""
	@echo "  make install  Install the package with development and documentation extras"
	@echo "  make test     Run release guard tests"
	@echo "  make docs     Build Sphinx documentation with warnings as errors"
	@echo "  make build    Build PyPI source and wheel artifacts"
	@echo "  make check    Validate built artifacts with Twine"
	@echo "  make clean    Remove local build, cache, and documentation artifacts"

install:
	$(PYTHON) -m pip install -e .[dev,docs]

test:
	$(PYTHON) -m pytest tests/test_package_release.py -q

docs:
	$(PYTHON) -m sphinx -W -b html docs docs/_build/html

build:
	$(PYTHON) -m build

check:
	$(PYTHON) -m twine check dist/*

clean:
	rm -rf build dist htmlcov docs/_build .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
