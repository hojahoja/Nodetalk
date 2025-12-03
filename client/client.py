# client/client.py

import asyncio
import json

import websockets

# Hard-coded server details
SERVER_HOST = "svm-11.cs.helsinki.fi"  # change here if needed (e.g. "localhost" with SSH tunnel)
DEFAULT_PORT = 9000                    # must match NT_PORT / server port


async def send_loop(websocket: websockets.WebSocketClientProtocol, sender: str) -> None:
    """
    Read lines from stdin and send them as chat messages.
    Runs until the user types /quit or /exit.
    """
    print("Type your messages and press Enter to send.")
    print("Type /quit or /exit to close the connection.\n")

    while True:
        # input() is blocking, so run it in a thread to avoid blocking the event loop
        text = await asyncio.to_thread(input, "> ")
        text = text.strip()

        if not text:
            continue

        if text.lower() in ("/quit", "/exit"):
            print("[client] Closing chat...")
            break

        msg = {
            "type": "chat",
            "from": sender,
            "text": text,
        }

        await websocket.send(json.dumps(msg))
        print(f"[{sender}] sent: {text}")


async def receive_loop(websocket: websockets.WebSocketClientProtocol) -> None:
    """
    Listen for any messages from the server and print them.

    Right now the server mainly sends:
      - 'ack' messages for replicated chats between peers.
      - In the future it could also send 'chat' messages back to clients.
    """
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[server] {raw}")
                continue

            msg_type = msg.get("type")

            if msg_type == "ack":
                print(f"[server] ack for message id={msg.get('id')}")
            elif msg_type == "chat":
                # If later we broadcast chats back to clients, handle them here.
                print(f"[chat] {msg.get('from')}: {msg.get('text')}")
            else:
                print(f"[server] {msg}")
    except websockets.ConnectionClosed:
        print("[client] Connection closed by server.")


async def run_client() -> None:
    # Ask the user for a display name once
    sender = input("Enter your name: ").strip() or "anonymous"

    uri = f"ws://{SERVER_HOST}:{DEFAULT_PORT}"
    print(f"[client:{sender}] Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as websocket:
            print(f"[client:{sender}] Connected. You can start chatting.")

            # One task for sending, one for receiving
            send_task = asyncio.create_task(send_loop(websocket, sender))
            recv_task = asyncio.create_task(receive_loop(websocket))

            # Wait until either sending or receiving finishes
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the other task if still running
            for task in pending:
                task.cancel()

    except Exception as e:
        print(f"[client:{sender}] Error: {e}")


def main() -> None:
    asyncio.run(run_client())


if __name__ == "__main__":
    main()
