#!/bin/bash

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIABLES="${SOURCE_DIR}/.env"
PROXY="melkki.cs.helsinki.fi"

if [[ -f "$VARIABLES" ]]; then
    source "$VARIABLES"
fi

if [[ -z "$REMOTE_USER" ]]; then
    echo "REMOTE_USER variable not set"
fi


if [[ -z "$NT_PORT" ]]; then
    echo "NT_PORT variable not set"
fi


ssh \
  -L 9000:svm-11.cs.helsinki.fi:9010 \
  -L 9001:svm-11-2.cs.helsinki.fi:9010 \
  -L 9002:svm-11-3.cs.helsinki.fi:9010 \
  ${REMOTE_USER}@${PROXY}