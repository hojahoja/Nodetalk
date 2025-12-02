#!/bin/bash

GREEN="\033[0;32m"
REGULAR="\033[0m"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIABLES="${SOURCE_DIR}/.env"

# Load or prompt for REMOTE_USER
if [[ -f "$VARIABLES" ]]; then
    source "$VARIABLES"
fi

if [[ -z "$REMOTE_USER" ]]; then
    read -p "Enter your remote username: " REMOTE_USER
    echo "REMOTE_USER=\"$REMOTE_USER\"" >> "$VARIABLES"
fi

# Resolve path to the script
DEST_DIR="Nodetalk"
PROXY="melkki.cs.helsinki.fi"
DESTINATION="svm-11.cs.helsinki.fi"

# Files not to be uploaded to the servers
EXCLUDES=(
    "--exclude=__pycache__"
    "--exclude=.git*"
    "--exclude=README.md"
    "--exclude=.venv"
    "--exclude=$(basename "$0")"
    "--exclude=start.sh"
    "--exclude=stop.sh"
    "--exclude=pid_svm-11*"
)

# Sync command
update-nd () {
    rsync -avz \
    "${EXCLUDES[@]}" \
    -e "ssh -J ${REMOTE_USER}@${PROXY}" \
    "$SOURCE_DIR/" \
    "${REMOTE_USER}@${DESTINATION}:${DEST_DIR}/"
}

# Run rsync for all nodes
for DESTINATION in svm-11{,-2,-3}.cs.helsinki.fi; do
    echo -e "${GREEN}updating${REGULAR} $DESTINATION..."
    update-nd
done

