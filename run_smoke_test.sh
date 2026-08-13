#!/bin/bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 tests/smoke_test.py
