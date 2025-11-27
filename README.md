````markdown
# Nodetalk – Minimal 3-Node Prototype

Nodetalk is a small distributed systems prototype for the UH Distributed Systems course.

The current version does exactly one thing:

> Run the same Python program on three different UH servers so that all three nodes
> connect to each other over WebSockets and exchange a small “hello” message.

---

## 1. What the code does

We assume exactly three fixed nodes:

- Node **A** on `svm-11.cs.helsinki.fi`
- Node **B** on `svm-11-2.cs.helsinki.fi`
- Node **C** on `svm-11-3.cs.helsinki.fi`

Every node:

- runs a WebSocket **server** on port `9000`
- opens outgoing WebSocket **connections** to the other two nodes
- sends a small JSON `"hello"` message when a connection is created
- prints every message it receives

There is no leader, no database, and no Redis yet.

### ASCII diagram

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
- When a connection is established, the client side sends a JSON {"type": "hello", ...}.
- The server side prints all received messages.
````

---

## 2. Code layout

```text
main.py                # entrypoint; parses --node-id and starts the node
nodetalk/
  __init__.py          # empty, marks this as a Python package
  config.py            # static mapping of node IDs to svm servers and port
  network.py           # WebSocket server + outgoing connections + hello messages
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

### 4.3 Expected output

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

If all three nodes show “Sent hello …” and “Received …” messages involving the other nodes, the basic 3-node communication is working.

```
```
