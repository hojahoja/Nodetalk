# nodetalk/network.py

import asyncio
import json

import websockets

from .config import NODES, PORT

# Simple in-memory message list for this node.
# Later this will become a replicated log + state machine.
MESSAGES = []  # list of dicts: {"type": "chat", "from": ..., "text": ..., ...}


async def broadcast_chat_to_peers(node_id: str, msg: dict) -> None:
    """
    Send a chat message to all other peers once.

    We mark the message as 'replicated': true so that receivers
    know this came from another peer and do not forward it again.
    """
    # Make a copy so we don't mutate the original structure in MESSAGES.
    out_msg = dict(msg)
    out_msg["replicated"] = True
    payload = json.dumps(out_msg)

    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue  # don't send to ourselves

        uri = f"ws://{peer_host}:{PORT}"
        try:
            print(f"[{node_id}] Broadcasting chat to {peer_id} at {uri}")
            async with websockets.connect(uri) as websocket:
                await websocket.send(payload)
        except Exception as e:
            print(f"[{node_id}] Failed to broadcast to {peer_id}: {e}")


async def handle_incoming(websocket, node_id: str):
    """
    Handle incoming messages from other peers or clients.

    For now:
      - print everything
      - if it's a chat message, store it in MESSAGES
      - if it's a *client-originated* chat (no 'replicated' flag),
        broadcast it once to the other peers
    """
    remote = websocket.remote_address
    print(f"[{node_id}] Incoming connection from {remote}")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{node_id}] Received non-JSON: {raw!r}")
                continue

            msg_type = msg.get("type")

            if msg_type == "chat":
                # Store chat messages locally
                MESSAGES.append(msg)
                print(
                    f"[{node_id}] CHAT from {msg.get('from')}: {msg.get('text')!r} "
                    f"(total messages here: {len(MESSAGES)})"
                )

                # If this chat has no 'replicated' flag, it came from a client
                # (or from outside the cluster). We broadcast it to peers.
                if not msg.get("replicated", False):
                    # Fire-and-forget broadcast; don't block this connection
                    asyncio.create_task(broadcast_chat_to_peers(node_id, msg))

            else:
                # e.g. "hello" messages between peers
                print(f"[{node_id}] Received message: {msg}")

    except websockets.ConnectionClosed:
        print(f"[{node_id}] Incoming connection closed from {remote}")


async def connect_to_peer(node_id: str, peer_id: str, peer_host: str):
    """
    Outgoing connection loop to a single peer.

    Keeps trying to connect. Once connected:
      - send one 'hello' JSON message
      - print anything we receive
    """
    uri = f"ws://{peer_host}:{PORT}"

    while True:
        try:
            print(f"[{node_id}] Trying to connect to peer {peer_id} at {uri}")
            async with websockets.connect(uri) as websocket:
                hello = {
                    "type": "hello",
                    "from": node_id,
                    "to": peer_id,
                }
                await websocket.send(json.dumps(hello))
                print(f"[{node_id}] Sent hello to {peer_id}")

                async for raw in websocket:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        print(f"[{node_id}] Received non-JSON from {peer_id}: {raw!r}")
                        continue

                    print(f"[{node_id}] Received from {peer_id}: {msg}")

        except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as e:
            print(f"[{node_id}] Could not connect to {peer_id} ({e}), retrying in 3s...")
            await asyncio.sleep(3)
        except websockets.ConnectionClosed:
            print(f"[{node_id}] Connection to {peer_id} closed, retrying in 3s...")
            await asyncio.sleep(3)


async def run_node(node_id: str):
    """
    Start this node:

      1. WebSocket server on PORT
      2. Outgoing connections to all other peers
    """
    if node_id not in NODES:
        raise SystemExit(f"Unknown node_id {node_id!r}. Use one of {list(NODES.keys())}")

    print(f"[{node_id}] Starting WebSocket server on port {PORT}...")

    # Start WebSocket server. Bind to all interfaces.
    # websockets.serve(handler, ...) calls handler(conn) with a single connection arg.
    server = await websockets.serve(
        lambda conn, nid=node_id: handle_incoming(conn, nid),
        host="0.0.0.0",
        port=PORT,
    )

    # Start outgoing connection tasks to other peers (for hello/debugging).
    peer_tasks = []
    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue
        peer_tasks.append(asyncio.create_task(connect_to_peer(node_id, peer_id, peer_host)))

    print(f"[{node_id}] Ready. Peers: {[p for p in NODES.keys() if p != node_id]}")

    try:
        await asyncio.gather(*peer_tasks)
    finally:
        server.close()
        await server.wait_closed()
