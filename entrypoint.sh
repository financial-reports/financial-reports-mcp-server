#!/bin/bash
set -e

python scripts/generate_mcp_tools.py

exec "$@"