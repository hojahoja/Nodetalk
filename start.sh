#!/bin/bash

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIABLES="${SOURCE_DIR}/.env"

# Load REMOTE_USER
if [[ -f "$VARIABLES" ]]; then
    source "$VARIABLES"
fi

if [[ -z "$REMOTE_USER" ]]; then
    echo "REMOTE_USER variable not set"
fi

PROXY="melkki.cs.helsinki.fi"

# Assing unique values for each server commands
declare -A SERVER_CMDS
SERVER_CMDS["svm-11.cs.helsinki.fi"]=".local/bin/uv run \
    --project Nodetalk Nodetalk/main.py --node-id A"
SERVER_CMDS["svm-11-2.cs.helsinki.fi"]=".local/bin/uv run \
    --project Nodetalk Nodetalk/main.py --node-id B"
SERVER_CMDS["svm-11-3.cs.helsinki.fi"]=".local/bin/uv run \
    --project Nodetalk Nodetalk/main.py --node-id C"

# Run the commands and create .txt file with the pid inside
for DEST in "${!SERVER_CMDS[@]}"; do
    CMD="${SERVER_CMDS[$DEST]}"
    echo "Starting on $DEST with: $CMD"
    ssh -J "${REMOTE_USER}@${PROXY}" "${REMOTE_USER}@${DEST}" \
        "nohup $CMD > main.log 2>&1 & echo \$!" > "pid_${DEST}.txt"
done
