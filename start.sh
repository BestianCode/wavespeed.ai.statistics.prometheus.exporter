#!/bin/bash

set -e

#export WS_AI_TOKEN="..."

#export PORT="8080"

while true; do
    python3 main.py || true
    sleep 1
done
