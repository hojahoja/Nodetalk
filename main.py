# main.py

import argparse
import asyncio

from nodetalk.network import run_node
from nodetalk.config import NODES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nodetalk simple peer")
    parser.add_argument(
        "--node-id",
        required=True,
        choices=list(NODES.keys()),
        help="ID of this node (e.g. A, B, C)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_node(args.node_id))


if __name__ == "__main__":
    main()
