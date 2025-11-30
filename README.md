````markdown
# Nodetalk – Minimal 3-Node Prototype

Nodetalk is a small distributed systems prototype for the UH Distributed Systems course.

The current version does two main things:

1. Runs the same Python server on three UH servers so that all three nodes
   connect to each other over WebSockets and exchange small “hello” messages.
2. Accepts `chat` messages from a separate Python client on any node and
   replicates those chat messages to all three nodes (in memory).

There is still no leader, no global ordering, no database, and no Redis yet.
This is a minimal communication + replication skeleton.

---

## 1. What the code does

We assume exactly three fixed nodes:

- Node **A** on `svm-11.cs.helsinki.fi`
- Node **B** on `svm-11-2.cs.helsinki.fi`
- Node **C** on `svm-11-3.cs.helsinki.fi`

Every **server node**:

- runs a WebSocket **server** on port `9000`
- opens outgoing WebSocket **connections** to the other two nodes (for `hello` messages)
- keeps an in-memory list `MESSAGES` of all `chat` messages it has seen
- accepts WebSocket connections from a **client** (Python CLI, later React)
- when it receives a `chat` from a client:
  - appends it to its local `MESSAGES`
  - broadcasts it once to the other two nodes
- when it receives a **replicated** `chat` from another node:
  - appends it to its local `MESSAGES`
  - does not forward it further (to avoid loops)

So after one client sends a `chat` to any node, **all three nodes** have that message in memory.

### 1.1 Server-to-server “hello” connections

```text
        ws://svm-11:9000             ws://svm-11-2:9000             ws://svm-11-3:9000

  +-------------------+         +-------------------+         +-------------------+
  |   Node A (svm-11) |         |  Node B (svm-11-2)|         |  Node C (svm-11-3)|
  |                   |         |                   |         |                   |
  |  WS server :9000  |         |  WS server :9000  |         |  WS server :9000  |
  |        ^          |         |        ^          |         |        ^          |
  |        |          |         |        |          |         |        |          |
  |   +----+------+   |         |   +----+------+   |         |   +----+------+   |
  |   | outgoing  |---+-------->|   | outgoing  |---+-------->|   | outgoing  |   |
  |   | to B,C    |<------------+   | to A,C    |<------------+   | to A,B    |   |
  |   +-----------+   |         |   +-----------+   |         |   +-----------+   |
  +-------------------+         +-------------------+         +-------------------+

Legend:
- Each node runs a WebSocket server on port 9000.
- Each node also opens outgoing WebSocket connections to the other two nodes.
- When a connection is established, the client side sends JSON like {"type": "hello", ...}.
- The server side prints all received messages.
````

### 1.2 Client-to-server chat + replication

Logical flow:

```text
[Client] -- chat --> [Node X] -- replicated chat --> [Node Y]
                               \-- replicated chat --> [Node Z]
```

* Client sends:

  ```json
  { "type": "chat", "from": "sender-name", "text": "some message" }
  ```

* Receiving node stores it and sends a copy with `"replicated": true` to the other nodes.

* Replicated messages are stored but not re-broadcast.

All nodes converge to the same sequence of messages in `MESSAGES`, but there is no strict global ordering or durability yet.

---

## 2. Code layout

```text
main.py                # entrypoint; parses --node-id and starts the server node

nodetalk/
  __init__.py          # empty, marks this as a Python package
  config.py            # static mapping of node IDs to svm servers and port
  network.py           # WebSocket server, peer connections, in-memory MESSAGES, chat replication

client/
  client.py            # simple CLI client: connect to a node and send one chat message
```

---

## 3. Dependencies

Python packages:

* `websockets`

Install with `uv` (recommended in this repo):

```bash
uv add websockets
```

Or with `pip`:

```bash
pip install websockets
```

---

## 4. How to run on the UH course servers

All three VMs are reachable only through the UH gateway `melkki.cs.helsinki.fi`.
Example username here is `kkumar`.

### 4.1 Clone the repo (first time only)

From your laptop:

```bash
ssh kkumar@melkki.cs.helsinki.fi
```

Then, from `melkki`, for each server:

```bash
ssh kkumar@svm-11.cs.helsinki.fi
git clone https://github.com/hojahoja/Nodetalk.git
cd Nodetalk
uv sync   # or ensure 'websockets' is installed
```

Repeat the same on:

```bash
ssh kkumar@svm-11-2.cs.helsinki.fi
ssh kkumar@svm-11-3.cs.helsinki.fi
```

### 4.2 Start the three nodes (three terminals)

Open three separate SSH sessions:

**Node A – `svm-11`**

```bash
ssh kkumar@melkki.cs.helsinki.fi
ssh kkumar@svm-11.cs.helsinki.fi
cd Nodetalk
uv run main.py --node-id A    # or: python main.py --node-id A
```

**Node B – `svm-11-2`**

```bash
ssh kkumar@melkki.cs.helsinki.fi
ssh kkumar@svm-11-2.cs.helsinki.fi
cd Nodetalk
uv run main.py --node-id B    # or: python main.py --node-id B
```

**Node C – `svm-11-3`**

```bash
ssh kkumar@melkki.cs.helsinki.fi
ssh kkumar@svm-11-3.cs.helsinki.fi
cd Nodetalk
uv run main.py --node-id C    # or: python main.py --node-id C
```

### 4.3 Expected output (servers)

On each node you should see logs similar to:

```text
[A] Starting WebSocket server on port 9000...
[A] Ready. Peers: ['B', 'C']
[A] Trying to connect to peer B at ws://svm-11-2.cs.helsinki.fi:9000
[A] Trying to connect to peer C at ws://svm-11-3.cs.helsinki.fi:9000
[A] Sent hello to B
[A] Received from B: {'type': 'hello', 'from': 'B', 'to': 'A'}
...
```

Once you start sending `chat` messages (explained below), you will also see lines like:

```text
[A] CHAT from kamlesh: 'hello from client' (total messages here: 1)
[A] Broadcasting chat to B at ws://svm-11-2.cs.helsinki.fi:9000
[A] Broadcasting chat to C at ws://svm-11-3.cs.helsinki.fi:9000

[B] CHAT from kamlesh: 'hello from client' (total messages here: 1)
[C] CHAT from kamlesh: 'hello from client' (total messages here: 1)
```

If all three nodes show matching `CHAT` logs with the same text and increasing `total messages here`, basic replication is working.

---

### 4.4 With Shell Scripts

Run `serverpush.sh` to update the server with local changes from your files. On first run it will ask for your username and add them to a local .env file. On subsequent runs it will check for your username in the .env.

`start.sh` will start the main process on each server with unique node ID and leaves them running. It will create a .txt file to track the process id on each server.

`stop.sh` will check all the create .txt files and close the running processes
on each server. After closing each server the corresponding .txt file will be deleted.

---

## 5. How to send chat messages (CLI client on svm)

The Python client sends a single `chat` message to one server node.

From any of the three svm nodes (e.g. `svm-11`), with the servers already running:

```bash
ssh kkumar@melkki.cs.helsinki.fi
ssh kkumar@svm-11.cs.helsinki.fi
cd Nodetalk
```

Send a chat to **node A** (`svm-11`):

```bash
uv run client/client.py \
  --server-host svm-11.cs.helsinki.fi \
  --sender kamlesh \
  --text "hello from svm-11"
```

Send a chat to **node B** (`svm-11-2`):

```bash
uv run client/client.py \
  --server-host svm-11-2.cs.helsinki.fi \
  --sender kamlesh \
  --text "hello to node B"
```

Send a chat to **node C** (`svm-11-3`):

```bash
uv run client/client.py \
  --server-host svm-11-3.cs.helsinki.fi \
  --sender kamlesh \
  --text "hello to node C"
```

After any of these commands:

* The target node logs the `CHAT` and broadcasts it.
* The other two nodes log the replicated `CHAT`.
* Each node’s `MESSAGES` list grows by one.

---

## 6. Optional: running the client from your own laptop (SSH tunnel)

The svm machines are on an internal UH network, so direct WebSocket from your laptop to `svm-11:9000` will usually time out.

You can use SSH port forwarding to expose a node locally:

On your **local machine**:

```bash
ssh -L 9000:svm-11.cs.helsinki.fi:9000 kkumar@melkki.cs.helsinki.fi
```

Leave this terminal open. Now `ws://localhost:9000` on your laptop is forwarded to `svm-11:9000`.

In another local terminal (with a local clone of the repo):

```bash
cd Nodetalk
uv run client/client.py \
  --server-host localhost \
  --port 9000 \
  --sender laptop \
  --text "hello from my laptop"
```

Node A (`svm-11`) will see the `CHAT` and replicate it to B and C exactly as if the client were running on one of the svm servers.

You can also forward all three nodes if needed:

```bash
ssh \
  -L 9000:svm-11.cs.helsinki.fi:9000 \
  -L 9001:svm-11-2.cs.helsinki.fi:9000 \
  -L 9002:svm-11-3.cs.helsinki.fi:9000 \
  kkumar@melkki.cs.helsinki.fi
```

Then:

* Node A: `localhost:9000`
* Node B: `localhost:9001`
* Node C: `localhost:9002`

```
```
