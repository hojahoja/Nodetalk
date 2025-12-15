import asyncio
import json
import websockets

# Default chat server location
SERVER_HOST = "localhost"
DEFAULT_PORT = 9000


async def send_loop(websocket: websockets.WebSocketClientProtocol, sender: str) -> None:
    # Keeps reading what you type and sends it to everyone else
    print("Type your messages and press Enter to send.")
    print("Type /quit or /exit to close the connection.\n")

    while True:
        # Grab user input without freezing the rest of the program
        text = await asyncio.to_thread(input, "> ")
        text = text.strip()

        if not text:
            continue

        if text.lower() in ("/quit", "/exit"):
            print("[client] Closing chat...")
            break

        # Prepare the message we want to share
        msg = {
            "type": "chat",
            "from": sender,
            "text": text,
        }

        await websocket.send(json.dumps(msg))


async def receive_loop(websocket: websockets.WebSocketClientProtocol) -> None:
    # Listens for anything coming back from the chat
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
                print(f"[chat] {msg.get('from')}: {msg.get('text')}")
            else:
                print(f"[server] {msg}")
    except websockets.ConnectionClosed:
        print("[client] Connection closed by server.")


async def run_client() -> None:
    # Opens the chat session and keeps the background tasks alive
    sender = input("Enter your name: ").strip() or "anonymous"

    uri = f"ws://{SERVER_HOST}:{DEFAULT_PORT}"
    print(f"[client:{sender}] Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as websocket:
            print(f"[client:{sender}] Connected. You can start chatting.")

            # Let the server know who just joined
            await websocket.send(json.dumps({
                "type": "join",
                "from": sender,
            }))

            # Run sending and receiving at the same time
            send_task = asyncio.create_task(send_loop(websocket, sender))
            recv_task = asyncio.create_task(receive_loop(websocket))

            # Watch for whichever side finishes first
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Stop anything still running in the background
            for task in pending:
                task.cancel()

    except Exception as e:
        print(f"[client:{sender}] Error: {e}")


def main() -> None:
    asyncio.run(run_client())


if __name__ == "__main__":
    main()
