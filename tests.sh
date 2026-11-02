#!/bin/sh
set -eu
src=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
sh -n "$src/beastcord-launcher"
python3 -I "$src/test-manager.py"
python3 -I "$src/test-launch.py"
