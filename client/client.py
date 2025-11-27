# client/client.py

import argparse
import asyncio
import json

import websockets

DEFAULT_PORT = 9000  # same as server PORT


async def send_chat(server_host: str, port: int, sender: str, text: str):
    uri = f"ws://{server_host}:{port}"
    print(f"[client:{sender}] Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as websocket:
            msg = {
                "type": "chat",
                "from": sender,
                "text": text,
            }
            await websocket.send(json.dumps(msg))
            print(f"[client:{sender}] Sent chat: {text!r}")

            # Optionally: wait briefly to see if server sends something back
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                print(f"[client:{sender}] Received from server: {response}")
            except asyncio.TimeoutError:
                # No response is also fine for now
                pass

    except Exception as e:
        print(f"[client:{sender}] Error: {e}")


def parse_args():
    parser = argparse.ArgumentParser(description="Simple Nodetalk chat client")
    parser.add_argument(
        "--server-host",
        required=True,
        help="Hostname of the server to connect to, e.g. svm-11.cs.helsinki.fi",
    )
    parser.add_argument(
        "--sender",
        default="cli",
        help="Logical sender name (shown in messages)",
    )
    parser.add_argument(
        "--text",
        required=True,
        help="Chat text to send",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"WebSocket port (default {DEFAULT_PORT})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    asyncio.run(send_chat(args.server_host, args.port, args.sender, args.text))


if __name__ == "__main__":
    main()
