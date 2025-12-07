# nodetalk/network.py

import asyncio
import json
from uuid import uuid4

import websockets

from .config import NODES, PORT

# Log: ordered list of entries with commit status
LOG = []

# Committed messages: only these are visible to clients
MESSAGES = []

# Metadata
COMMITTED_INDEX = -1  # Highest log index that is committed
LEADER_ID = "A"  # Static for now. Leader election can call set_leader()

# Track active client connections (for future push notifications)
ACTIVE_CLIENTS = set()

async def broadcast_chat(message: dict) -> None:
    """
    Send a chat message to all currently connected clients on this node.
    """
    if not ACTIVE_CLIENTS:
        return

    payload = json.dumps(message)
    dead = []

    # Iterate over a copy to avoid modification during iteration
    for ws in list(ACTIVE_CLIENTS):
        try:
            await ws.send(payload)
        except Exception:
            # Connection is probably dead; clean it up
            dead.append(ws)

    for ws in dead:
        ACTIVE_CLIENTS.discard(ws)



def get_leader() -> str:
    """Get current leader. Called by election algorithm and replication logic."""
    return LEADER_ID


def set_leader(node_id: str) -> None:
    """Set leader. Can be called by election algorithm when leader changes."""
    global LEADER_ID
    LEADER_ID = node_id
    print(f"[network] Leader is now {node_id}")


def entry_to_message(entry: dict) -> dict:
    """Convert log entry to message dict for MESSAGES list."""
    return {
        "id": entry.get("id"),
        "type": entry.get("type"),
        "from": entry.get("from"),
        "text": entry.get("text"),
    }


async def replicate_to_followers(node_id: str, entry: dict) -> bool:
    """
    Leader: replicate entry to all followers and wait for majority ACKs.

    Returns True if majority (including self) ACKed, False otherwise.
    For 3 nodes, need 2 ACKs total (self + 1 follower).
    """
    ack_count = 1  # Leader always acks itself
    total_nodes = len(NODES)
    majority = (total_nodes // 2) + 1

    payload = json.dumps(
        {
            "type": "replicate",
            "entry": entry,
        }
    )

    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue

        uri = f"ws://{peer_host}:{PORT}"
        try:
            print(f"[{node_id}] Replicating entry {entry['id']} to {peer_id}")
            async with websockets.connect(uri, close_timeout=2.0) as ws:
                await ws.send(payload)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    resp = json.loads(raw)
                    if resp.get("type") == "ack" and resp.get("entry_id") == entry["id"]:
                        ack_count += 1
                        print(f"[{node_id}] ACK from {peer_id} for {entry['id']}")
                except asyncio.TimeoutError:
                    print(f"[{node_id}] No ACK from {peer_id} for {entry['id']}")
        except Exception as e:
            print(f"[{node_id}] Failed to replicate to {peer_id}: {e}")

    has_majority = ack_count >= majority
    print(
        f"[{node_id}] Entry {entry['id']}: {ack_count}/{total_nodes} ACKs. Majority: {has_majority}"
    )
    return has_majority


async def notify_commit(node_id: str, entry: dict) -> None:
    """
    Leader: notify followers that an entry is committed.
    Followers will then apply it to their MESSAGES list.
    """
    payload = json.dumps(
        {
            "type": "commit",
            "entry_id": entry["id"],
        }
    )

    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue
        uri = f"ws://{peer_host}:{PORT}"
        try:
            async with websockets.connect(uri, close_timeout=1.0) as ws:
                await ws.send(payload)
                print(f"[{node_id}] Notified {peer_id} to commit {entry['id']}")
        except Exception as e:
            print(f"[{node_id}] Failed to notify commit to {peer_id}: {e}")


async def forward_to_leader(node_id: str, chat_msg: dict) -> None:
    """
    Follower: forward client chat to the leader.
    Leader will handle replication and commit.
    """
    leader = get_leader()
    if leader == node_id:
        # We are the leader, shouldn't happen
        return

    leader_host = NODES.get(leader)
    if not leader_host:
        print(f"[{node_id}] ERROR: Unknown leader {leader}")
        return

    uri = f"ws://{leader_host}:{PORT}"
    try:
        print(f"[{node_id}] Forwarding chat to leader {leader}")
        async with websockets.connect(uri, close_timeout=2.0) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "forward",
                        "chat": chat_msg,
                    }
                )
            )
    except Exception as e:
        print(f"[{node_id}] Failed to forward to leader {leader}: {e}")


async def _process_leader_chat(node_id: str, chat_msg: dict, source: str = "client") -> None:
    """
    Leader: create log entry, replicate to followers, and commit if majority achieved.

    Args:
        node_id: The leader node ID
        chat_msg: The chat message dict with "from" and "text" fields
        source: "client" or "forwarded" for logging purposes
    """
    global COMMITTED_INDEX

    # Create log entry
    entry = {
        "id": str(uuid4()),
        "type": "chat",
        "from": chat_msg.get("from", "unknown"),
        "text": chat_msg.get("text", ""),
        "committed": False,
    }
    LOG.append(entry)
    print(f"[{node_id}] Leader appended {source} entry {entry['id']} to log")

    # Replicate to followers
    has_majority = await replicate_to_followers(node_id, entry)

    if has_majority:
        # Commit: mark as committed and apply to state machine
        COMMITTED_INDEX = len(LOG) - 1
        entry["committed"] = True
        print(f"[{node_id}] Entry {entry['id']} committed (majority achieved)")

        # Apply to state machine (MESSAGES)
        msg_to_store = entry_to_message(entry)
        MESSAGES.append(msg_to_store)
        print(
            f"[{node_id}] CHAT from {entry.get('from')}: {entry.get('text')!r} "
            f"(total messages: {len(MESSAGES)})"
        )

        # broadcast committed chat to this node's clients
        await broadcast_chat(msg_to_store)

        # Notify followers to commit
        await notify_commit(node_id, entry)
    else:
        # Failed to get majority
        print(f"[{node_id}] Entry {entry['id']} FAILED to reach majority")


async def handle_incoming(websocket, node_id: str) -> None:
    """
    Handle incoming messages from other peers or clients.

    Message types:
      - "chat": client sends a chat (any node accepts)
      - "forward": follower forwards client chat to leader
      - "replicate": leader sends log entry to follower
      - "ack": follower acknowledges replication
      - "commit": leader tells follower to apply entry
      - "hello": peer greeting
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


            if msg_type == "join":
                # Client announces itself; register and send history
                ACTIVE_CLIENTS.add(websocket)
                print(f"[{node_id}] Client joined, sending {len(MESSAGES)} history messages")
                for message in MESSAGES:
                    await websocket.send(json.dumps(message))

            elif msg_type == "chat":
                # Client sends a chat message to this node
                if get_leader() != node_id:
                    # We are a follower, forward to leader
                    print(f"[{node_id}] Received client chat, forwarding to leader")
                    asyncio.create_task(forward_to_leader(node_id, msg))
                    continue

                # We are the LEADER: process the chat
                await _process_leader_chat(node_id, msg, source="client")
            

            elif msg_type == "forward":
                # Follower forwarded a client chat to us (the leader)
                chat_msg = msg.get("chat", {})
                print(f"[{node_id}] Received forwarded chat from follower")

                # Process as if client connected directly to leader
                await _process_leader_chat(node_id, chat_msg, source="forwarded")

            elif msg_type == "replicate":
                # FOLLOWER: receive replication from leader
                entry = msg.get("entry", {})
                entry_id = entry.get("id")

                # Check if already in log
                if entry_id not in [e["id"] for e in LOG]:
                    LOG.append(entry)
                    print(f"[{node_id}] Follower appended entry {entry_id} from leader")

                # ACK back to leader
                await websocket.send(
                    json.dumps(
                        {
                            "type": "ack",
                            "entry_id": entry_id,
                        }
                    )
                )

            elif msg_type == "commit":
                # FOLLOWER: leader tells us to commit entry
                entry_id = msg.get("entry_id")

                # Find entry in log and mark committed
                for entry in LOG:
                    if entry["id"] == entry_id:
                        entry["committed"] = True
                        COMMITTED_INDEX = LOG.index(entry)
                        print(f"[{node_id}] Entry {entry_id} committed by leader")

                        # Apply to state machine
                        msg_to_store = entry_to_message(entry)
                        if msg_to_store not in MESSAGES:
                            MESSAGES.append(msg_to_store)
                            print(
                                f"[{node_id}] CHAT from {entry.get('from')}: {entry.get('text')!r} "
                                f"(total messages: {len(MESSAGES)})"
                            )

                            # NEW: broadcast committed chat to this node's clients
                            await broadcast_chat(msg_to_store)
                        break


            elif msg_type == "hello":
                # Peer hello message (unchanged)
                print(f"[{node_id}] Received message: {msg}")

            else:
                print(f"[{node_id}] Unknown message type: {msg_type}")

        # # Temp logging
        # print(f"[{node_id}] Current committed messages:")
        # for message in MESSAGES:
        #     print(message)
        # # print current logs
        # print(f"[{node_id}] Current log entries:")
        # for log_entry in LOG:
        #     print(log_entry)

    except websockets.ConnectionClosed:
        print(f"[{node_id}] Incoming connection closed from {remote}")
    finally:
        # Remove this websocket from active clients if it was one
        ACTIVE_CLIENTS.discard(websocket)


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
    print(f"[{node_id}] Current leader: {get_leader()}")

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
