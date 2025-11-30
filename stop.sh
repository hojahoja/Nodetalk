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
DESTINATIONS=("svm-11.cs.helsinki.fi" "svm-11-2.cs.helsinki.fi" "svm-11-3.cs.helsinki.fi")

# Look for the pid in each destination.txt and kill the process
# on the server. Delete the pid destination.txt file after killing the process
for DEST in "${DESTINATIONS[@]}"; do
    if [[ -f "pid_${DEST}.txt" ]]; then
        PID=$(cat "pid_${DEST}.txt")
        echo "Stopping $DEST (PID $PID)..."
        ssh -J "${REMOTE_USER}@${PROXY}" "${REMOTE_USER}@${DEST}" "kill $PID"
        rm "pid_${DEST}.txt"
    fi
done
