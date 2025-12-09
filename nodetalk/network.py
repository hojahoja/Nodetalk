# nodetalk/network.py

import asyncio
import json
from uuid import uuid4
import time

import websockets

from .config import NODES, PORT

# Log: ordered list of entries with commit status
LOG = []
LOG_INDEX = {}  # id -> index in LOG for faster lookups and deduplication
COMMITTED_INDEX = -1  # Highest log index that is committed

# Committed messages: only these are visible to clients
MESSAGES = []

# Track active client connections (for future push notifications)
ACTIVE_CLIENTS = set()

LEADER_ID = None
IS_LEADER = False
LAST_HEARTBEAT = time.time()
ELECTION_IN_PROGRESS = False

PEER_CONNECTIONS = {}


async def leader_heartbeat(node_id: str):
    """Runs only on the leader: broadcasts heartbeat every second."""
    global LEADER_ID, IS_LEADER

    while True:
        await asyncio.sleep(1.0)
        if IS_LEADER:
            # Heartbeat contains committed index for followers to catch up
            msg = {"type": "heartbeat", "from": node_id, "committed_index": COMMITTED_INDEX}
            await broadcast_control_to_peers(node_id, msg)


async def broadcast_control_to_peers(node_id: str, msg: dict):
    payload = json.dumps(msg)
    dead_peers = []
    for peer_id, websocket in PEER_CONNECTIONS.items():
        if peer_id == node_id:
            continue
        try:
            await websocket.send(payload)
        except Exception:
            print(f"[{node_id}] Failed to send heartbeat to {peer_id}")
            dead_peers.append(peer_id)

    for peer_id in dead_peers:
        PEER_CONNECTIONS.pop(peer_id, None)


async def monitor_heartbeat(node_id: str):
    global LAST_HEARTBEAT, IS_LEADER, LEADER_ID, ELECTION_IN_PROGRESS

    while True:
        await asyncio.sleep(2.0)

        if IS_LEADER:
            continue  # leader does not expect heartbeats

        # Check if leader has timed out
        time_since_heartbeat = time.time() - LAST_HEARTBEAT

        if not IS_LEADER and LEADER_ID is not None and time_since_heartbeat > 5.0:
            # Only start election if one isn't already in progress
            if not ELECTION_IN_PROGRESS:
                print(
                    f"[{node_id}] Leader timeout detected! Last heartbeat {time_since_heartbeat:.1f}s ago"
                )
                print(f"[{node_id}] Starting election...")
                asyncio.create_task(start_election(node_id))


def is_higher(node_a, node_b):
    return node_a > node_b


async def start_election(node_id: str):
    global ELECTION_IN_PROGRESS, IS_LEADER, LEADER_ID

    if ELECTION_IN_PROGRESS or IS_LEADER:
        print(f"[{node_id}] Election already in progress or I'm leader, skipping")
        return

    ELECTION_IN_PROGRESS = True
    print(f"[{node_id}] Sending ELECTION to higher nodes...")
    msg = {"type": "election", "from": node_id}

    heard_back = False

    for peer_id, peer_host in NODES.items():
        if is_higher(peer_id, node_id):
            # Try persistent connection first
            if peer_id in PEER_CONNECTIONS:
                try:
                    ws = PEER_CONNECTIONS[peer_id]
                    await ws.send(json.dumps(msg))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        r = json.loads(raw)
                        if r.get("type") == "election_ok":
                            heard_back = True
                            print(f"[{node_id}] Received election_ok from {peer_id} (persistent)")
                    except asyncio.TimeoutError:
                        print(f"[{node_id}] No response from {peer_id} (persistent)")
                    continue  # Success, skip fallback
                except Exception as e:
                    print(
                        f"[{node_id}] Persistent connection to {peer_id} failed: {e}, trying new connection"
                    )

            # Fallback to new connection if persistent failed or doesn't exist
            try:
                async with websockets.connect(f"ws://{peer_host}:{PORT}", close_timeout=2.0) as ws:
                    await ws.send(json.dumps(msg))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        r = json.loads(raw)
                        if r.get("type") == "election_ok":
                            heard_back = True
                            print(
                                f"[{node_id}] Received election_ok from {peer_id} (new connection)"
                            )
                    except asyncio.TimeoutError:
                        print(f"[{node_id}] No response from {peer_id} (new connection)")
            except Exception as e:
                print(f"[{node_id}] Could not reach {peer_id}: {e}")

    if not heard_back:
        print(f"[{node_id}] No higher nodes responded, becoming leader")
        await become_leader(node_id)
    else:
        print(f"[{node_id}] Higher node responded, waiting for coordinator/heartbeat...")
        await asyncio.sleep(5)

        # After waiting, check if we got a leader (via coordinator or heartbeat)
        if LEADER_ID is not None and not IS_LEADER:
            print(f"[{node_id}] Leader {LEADER_ID} established, canceling election")
            ELECTION_IN_PROGRESS = False
        elif not IS_LEADER and ELECTION_IN_PROGRESS:
            print(f"[{node_id}] No coordinator/heartbeat received, restarting election")
            ELECTION_IN_PROGRESS = False
            asyncio.create_task(start_election(node_id))
        else:
            ELECTION_IN_PROGRESS = False


async def handle_election(msg, node_id):
    global IS_LEADER, ELECTION_IN_PROGRESS

    sender = msg["from"]
    if is_higher(node_id, sender):
        print(f"[{node_id}] Received election from lower node {sender}")

        # If we're already the leader, just respond OK and send coordinator
        if IS_LEADER:
            print(f"[{node_id}] Already leader, sending coordinator announcement to {sender}")
            # The response will tell them we're alive
            # They should receive our heartbeats soon
            return {"type": "election_ok", "from": node_id}

        # If not leader and not in election, start our own election
        if not ELECTION_IN_PROGRESS:
            print(f"[{node_id}] Starting own election")
            asyncio.create_task(start_election(node_id))

        return {"type": "election_ok", "from": node_id}
    return None


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


async def become_leader(node_id: str):
    global IS_LEADER, LEADER_ID, ELECTION_IN_PROGRESS
    IS_LEADER = True
    LEADER_ID = node_id
    ELECTION_IN_PROGRESS = False

    print(f"[{node_id}] I am the new leader!")

    # Broadcast coordinator announcement
    msg = {"type": "coordinator", "from": node_id}
    await broadcast_control_to_peers(node_id, msg)


def entry_to_message(entry: dict) -> dict:
    """Convert log entry to message dict for MESSAGES list."""
    return {
        "id": entry.get("id"),
        "type": entry.get("type"),
        "from": entry.get("from"),
        "text": entry.get("text"),
    }


async def _replicate_to_single_peer(
    node_id: str, peer_id: str, peer_host: str, entry: dict
) -> bool:
    """Helper: replicate to one peer, return True if ACKed."""
    uri = f"ws://{peer_host}:{PORT}"
    payload = json.dumps({"type": "replicate", "entry": entry})

    try:
        async with websockets.connect(uri, close_timeout=2.0) as ws:
            await ws.send(payload)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                resp = json.loads(raw)
                if resp.get("type") == "ack" and resp.get("entry_id") == entry["id"]:
                    print(f"[{node_id}] ACK from {peer_id} for {entry['id']}")
                    return True
            except asyncio.TimeoutError:
                print(f"[{node_id}] No ACK from {peer_id} for {entry['id']}")
    except Exception as e:
        print(f"[{node_id}] Failed to replicate to {peer_id}: {e}")

    return False


async def replicate_to_followers(node_id: str, entry: dict) -> bool:
    """
    Leader: replicate entry to all followers IN PARALLEL and wait for majority ACKs.

    Returns True if majority (including self) ACKed, False otherwise.
    For 3 nodes, need 2 ACKs total (self + 1 follower).
    """
    ack_count = 1  # Leader always acks itself
    total_nodes = len(NODES)
    majority = (total_nodes // 2) + 1

    # Parallel replication to all followers
    tasks = []
    peer_ids = []
    for peer_id, peer_host in NODES.items():
        if peer_id != node_id:
            print(f"[{node_id}] Replicating entry {entry['id']} to {peer_id}")
            tasks.append(_replicate_to_single_peer(node_id, peer_id, peer_host, entry))
            peer_ids.append(peer_id)

    # Await all replication attempts
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for peer_id, result in zip(peer_ids, results):
            if result is True:
                ack_count += 1
            elif isinstance(result, Exception):
                print(f"[{node_id}] Exception replicating to {peer_id}: {result}")

    has_majority = ack_count >= majority
    print(
        f"[{node_id}] Entry {entry['id']}: {ack_count}/{total_nodes} ACKs. Majority: {has_majority}"
    )
    return has_majority


async def _notify_single_peer(node_id: str, peer_id: str, peer_host: str, entry_id: str) -> None:
    """Helper: notify one peer of commit (fire-and-forget)."""
    uri = f"ws://{peer_host}:{PORT}"
    payload = json.dumps({"type": "commit", "entry_id": entry_id})

    try:
        async with websockets.connect(uri, close_timeout=1.0) as ws:
            await ws.send(payload)
            print(f"[{node_id}] Notified {peer_id} to commit {entry_id}")
    except Exception as e:
        print(f"[{node_id}] Failed to notify commit to {peer_id}: {e}")


async def notify_commit(node_id: str, entry: dict) -> None:
    """
    Leader: notify followers that an entry is committed IN PARALLEL.
    Followers will then apply it to their MESSAGES list.
    """
    entry_id = entry["id"]

    # Parallel fire-and-forget notifications
    tasks = []
    for peer_id, peer_host in NODES.items():
        if peer_id != node_id:
            tasks.append(_notify_single_peer(node_id, peer_id, peer_host, entry_id))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


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
    LOG_INDEX[entry["id"]] = len(LOG) - 1
    print(f"[{node_id}] Leader appended {source} entry {entry['id']} to log (index {len(LOG)-1})")

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


async def sync_from_leader(node_id: str) -> None:
    """
    On node startup, request log from the current leader and catch up.
    Assumes leader is stable and authoritative.
    """
    global LOG, MESSAGES, COMMITTED_INDEX, LEADER_ID

    leader = get_leader()

    if leader is None:
        print(f"[{node_id}] No leader yet, skipping sync")
        return

    if leader == node_id:
        print(f"[{node_id}] I am the leader, skipping sync")
        return

    leader_host = NODES.get(leader)
    if not leader_host:
        print(f"[{node_id}] ERROR: Unknown leader {leader}")
        return

    print(f"[{node_id}] Starting log sync from leader {leader}...")

    uri = f"ws://{leader_host}:{PORT}"
    try:
        async with websockets.connect(uri, close_timeout=5.0) as ws:
            await ws.send(json.dumps({"type": "sync_request", "from": node_id}))

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                resp = json.loads(raw)

                if resp.get("type") == "sync_error":
                    print(f"[{node_id}] Sync failed: {resp.get('reason')}")
                    # Leader might be down, clear LEADER_ID
                    LEADER_ID = None
                    return

                if resp.get("type") != "sync_response":
                    print(f"[{node_id}] Unexpected response from leader: {resp.get('type')}")
                    return

                leader_log = resp.get("log", [])
                leader_committed_index = resp.get("committed_index", -1)

                print(f"[{node_id}] Received log from leader: {len(leader_log)} entries")

                # Replace our log with leader's log (leader is source of truth)
                LOG.clear()
                LOG.extend(leader_log)
                COMMITTED_INDEX = leader_committed_index

                # Rebuild LOG_INDEX from synced log
                LOG_INDEX.clear()
                for idx, entry in enumerate(LOG):
                    entry_id = entry.get("id")
                    if entry_id:
                        LOG_INDEX[entry_id] = idx

                # Apply committed entries to MESSAGES
                MESSAGES.clear()
                for i, entry in enumerate(LOG):
                    if i <= COMMITTED_INDEX and entry.get("committed", False):
                        msg = entry_to_message(entry)
                        MESSAGES.append(msg)

                print(f"[{node_id}] Sync complete: {len(MESSAGES)} committed messages")

            except asyncio.TimeoutError:
                print(f"[{node_id}] Sync request timed out, leader might be down")
                LEADER_ID = None

    except Exception as e:
        print(f"[{node_id}] Failed to sync from leader: {e}")
        LEADER_ID = None


async def handle_incoming(websocket, node_id: str) -> None:
    """
    Handle incoming messages from other peers or clients.

    Message types:
      - "join": client announces itself and requests history
      - "chat": client sends a chat (any node accepts)
      - "forward": follower forwards client chat to leader
      - "replicate": leader sends log entry to follower
      - "ack": follower acknowledges replication
      - "commit": leader tells follower to apply entry
      - "sync_request": peer requests log for catch-up (leader only responds)
      - "hello": peer greeting
    """

    global LOG, MESSAGES, COMMITTED_INDEX, LAST_HEARTBEAT, LEADER_ID, IS_LEADER, ELECTION_IN_PROGRESS

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

            elif msg_type == "sync_request":
                # Peer requests log for catch-up
                # Only leader should respond with authoritative log
                requester = msg.get("from", "unknown")

                if get_leader() != node_id:
                    # We are not the leader, reject sync request
                    print(f"[{node_id}] Sync request from {requester}, but I'm not the leader")
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "sync_error",
                                "reason": f"Not leader. Leader is {get_leader()}",
                            }
                        )
                    )
                else:
                    # We are the leader, send our authoritative log
                    print(f"[{node_id}] Sync request from {requester}, sending log")
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "sync_response",
                                "log": LOG,
                                "committed_index": COMMITTED_INDEX,
                            }
                        )
                    )

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

                # deduplication check
                if entry_id and entry_id not in LOG_INDEX:
                    LOG.append(entry)
                    LOG_INDEX[entry_id] = len(LOG) - 1
                    print(
                        f"[{node_id}] Follower appended entry {entry_id} from leader (index {len(LOG)-1})"
                    )

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

                # Look up entry in our log
                entry_idx = LOG_INDEX.get(entry_id)
                if entry_idx is not None and entry_idx < len(LOG):
                    entry = LOG[entry_idx]

                    if not entry.get("committed", False):  # Only commit once
                        entry["committed"] = True
                        COMMITTED_INDEX = entry_idx
                        print(
                            f"[{node_id}] Entry {entry_id} committed by leader (index {entry_idx})"
                        )

                        # Apply to state machine
                        msg_to_store = entry_to_message(entry)
                        MESSAGES.append(msg_to_store)
                        print(
                            f"[{node_id}] CHAT from {entry.get('from')}: {entry.get('text')!r} "
                            f"(total messages: {len(MESSAGES)})"
                        )

                        # broadcast committed chat to this node's clients
                        await broadcast_chat(msg_to_store)
                else:
                    print(f"[{node_id}] Commit entry {entry_id} not found in log")

            elif msg_type == "hello":
                # Peer hello message (unchanged)
                print(f"[{node_id}] Received message: {msg}")

            elif msg_type == "heartbeat":
                LAST_HEARTBEAT = time.time()
                LEADER_ID = msg["from"]

                # Check if we're behind leader
                leader_committed = msg.get("committed_index", -1)
                if leader_committed > COMMITTED_INDEX:
                    print(
                        f"[{node_id}] Behind leader ({COMMITTED_INDEX} < {leader_committed}), syncing..."
                    )
                    asyncio.create_task(sync_from_leader(node_id))

            elif msg_type == "election":
                resp = await handle_election(msg, node_id)
                if resp:
                    await websocket.send(json.dumps(resp))

            elif msg_type == "election_ok":
                ELECTION_IN_PROGRESS = True

            elif msg_type == "coordinator":
                sender = msg["from"]
                IS_LEADER = False
                LEADER_ID = sender
                ELECTION_IN_PROGRESS = False
                LAST_HEARTBEAT = time.time()
                print(
                    f"[{node_id}] Received coordinator announcement: {LEADER_ID} is now the leader"
                )

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
                PEER_CONNECTIONS[peer_id] = websocket

                hello = {"type": "hello", "from": node_id, "to": peer_id}
                await websocket.send(json.dumps(hello))
                print(f"[{node_id}] Sent hello to {peer_id}")

                async for raw in websocket:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    print(f"[{node_id}] Received from {peer_id}: {msg}")

        except Exception as e:
            print(f"[{node_id}] Could not connect to {peer_id} ({e}), retrying in 3s...")
            PEER_CONNECTIONS.pop(peer_id, None)  # Clear on error
            await asyncio.sleep(3)
        except websockets.ConnectionClosed:
            print(f"[{node_id}] Connection to {peer_id} closed, retrying...")
            PEER_CONNECTIONS.pop(peer_id, None)  # Clear on close
            await asyncio.sleep(3)
        finally:
            PEER_CONNECTIONS.pop(peer_id, None)


async def run_node(node_id: str):
    """
    Start this node:

      1. Sync log from leader (catch up after restart)
      2. WebSocket server on PORT
      3. Outgoing connections to all other peers
    """
    if node_id not in NODES:
        raise SystemExit(f"Unknown node_id {node_id!r}. Use one of {list(NODES.keys())}")

    print(f"[{node_id}] Starting WebSocket server on port {PORT}...")
    # print(f"[{node_id}] Current leader: {get_leader()}")

    # Start WebSocket server
    server = await websockets.serve(
        lambda conn, nid=node_id: handle_incoming(conn, nid),
        host="0.0.0.0",
        port=PORT,
    )

    # Start outgoing connection tasks to other peers
    peer_tasks = []
    for peer_id, peer_host in NODES.items():
        if peer_id == node_id:
            continue
        peer_tasks.append(asyncio.create_task(connect_to_peer(node_id, peer_id, peer_host)))

    asyncio.create_task(leader_heartbeat(node_id))
    asyncio.create_task(monitor_heartbeat(node_id))

    print(f"[{node_id}] Waiting 3 seconds for peer connections...")
    await asyncio.sleep(3)

    # Sync log from leader on startup (before accepting clients)
    await sync_from_leader(node_id)

    if LEADER_ID is None:
        print(f"[{node_id}] No leader found after sync, waiting 3 more seconds for heartbeats...")
        await asyncio.sleep(3)

        # Check again after waiting for heartbeats
        if LEADER_ID is None:
            print(f"[{node_id}] Still no leader, starting election")
            asyncio.create_task(start_election(node_id))
        else:
            print(f"[{node_id}] Received heartbeat from leader {LEADER_ID}, no election needed")

    print(f"[{node_id}] Ready. Peers: {[p for p in NODES.keys() if p != node_id]}")

    try:
        await asyncio.gather(*peer_tasks)
    finally:
        server.close()
        await server.wait_closed()
