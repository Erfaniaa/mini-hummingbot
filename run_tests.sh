#!/bin/bash
# Fast test runner - runs only fast unit tests by default

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# Run with timeout and skip slow tests by default
python -m pytest tests/ -q -m "not slow" --timeout=5 "$@" 2>&1 || \
python -m pytest tests/ -q "$@"

