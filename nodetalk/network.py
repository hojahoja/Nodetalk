# nodetalk/network.py

import asyncio
import json

import websockets

from .config import NODES, PORT


async def handle_incoming(websocket, node_id: str):
    """
    Handle incoming messages from other peers.

    For now: just print what we receive.
    Compatible with newer websockets versions where the handler
    is called with a single 'connection' argument.
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
    # Newer websockets versions call the handler with a single 'connection'
    # argument, so we wrap our handler to pass node_id via default arg.
    server = await websockets.serve(
        lambda conn, nid=node_id: handle_incoming(conn, nid),
        host="0.0.0.0",
        port=PORT,
    )

    # Start outgoing connection tasks to other peers.
    peer_tasks = []
    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue
        peer_tasks.append(asyncio.create_task(connect_to_peer(node_id, peer_id, peer_host)))

    print(f"[{node_id}] Ready. Peers: {[p for p in NODES.keys() if p != node_id]}")

    try:
        # Run until interrupted. The peer_tasks are infinite loops.
        await asyncio.gather(*peer_tasks)
    finally:
        server.close()
        await server.wait_closed()
