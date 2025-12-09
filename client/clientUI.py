# client/clientUI.py
#
# Streamlit UI client for Nodetalk.
# Run with: streamlit run client/clientUI.py

import asyncio
import json
import threading
import queue
import time
import uuid

import streamlit as st
import websockets

# Default server details (you can override in the sidebar)
SERVER_HOST = "localhost"  # change to "localhost" if needed
DEFAULT_PORT = 9000                    # must match NT_PORT / server port


# ------------------------------
# WebSocket worker (background)
# ------------------------------

async def ws_main(
    host: str,
    port: int,
    username: str,
    send_q: "queue.Queue[dict | None]",
    incoming_q: "queue.Queue[dict]",
) -> None:
    uri = f"ws://{host}:{port}"
    try:
        async with websockets.connect(uri) as websocket:
            # Join handshake: server will send full history
            await websocket.send(json.dumps({
                "type": "join",
                "from": username,
            }))
            incoming_q.put({
                "type": "system",
                "text": f"Connected to {uri} as {username}",
            })

            async def sender():
                while True:
                    try:
                        msg = send_q.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue

                    if msg is None:
                        # Shutdown signal
                        break

                    await websocket.send(json.dumps(msg))

            async def receiver():
                async for raw in websocket:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = {"type": "system", "text": raw}
                    incoming_q.put(msg)

            await asyncio.gather(sender(), receiver())

    except Exception as e:
        incoming_q.put({
            "type": "system",
            "text": f"Connection error: {e}",
        })


def start_ws_thread(host: str, port: int, username: str) -> None:
    """
    Start the background WebSocket thread.

    IMPORTANT: Do NOT access st.session_state inside the thread.
    Capture the queues as local variables and pass them in.
    """
    # Initialize queues in main thread
    if "send_queue" not in st.session_state:
        st.session_state.send_queue = queue.Queue()
    if "incoming_queue" not in st.session_state:
        st.session_state.incoming_queue = queue.Queue()

    send_q = st.session_state.send_queue
    incoming_q = st.session_state.incoming_queue

    def worker():
        asyncio.run(
            ws_main(
                host,
                port,
                username,
                send_q,
                incoming_q,
            )
        )

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    st.session_state.ws_thread = t
    st.session_state.connected = True


def drain_incoming() -> None:
    """
    Move messages from the background incoming_queue into
    session_state.messages, deduplicating by message id.
    """
    q = st.session_state.get("incoming_queue")
    if not q:
        return

    while True:
        try:
            msg = q.get_nowait()
        except queue.Empty:
            break

        msg_type = msg.get("type")
        if msg_type == "chat":
            msg_id = msg.get("id")
            if msg_id:
                # skip if already seen
                if msg_id in st.session_state.seen_ids:
                    continue
                st.session_state.seen_ids.add(msg_id)

        st.session_state.messages.append(msg)


# ------------------------------
# Streamlit UI
# ------------------------------

st.set_page_config(
    page_title="Nodetalk Chat",
    page_icon="💬",
    layout="centered",
)

# Initialize session state (main thread only)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()
if "connected" not in st.session_state:
    st.session_state.connected = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True  # default on

# Sidebar: connection settings
with st.sidebar:
    st.markdown("### Connection")
    host = st.text_input("Server host", value=SERVER_HOST)
    port = st.number_input("Port", value=DEFAULT_PORT, step=1)
    username = st.text_input(
        "Your name",
        value=st.session_state.username or "",
        placeholder="e.g. Alice",
    )
    connect_clicked = st.button("Connect / Reconnect")

    st.session_state.auto_refresh = st.checkbox(
        "Auto-refresh chat", value=st.session_state.auto_refresh
    )

    if connect_clicked:
        if not username.strip():
            st.warning("Please enter a name before connecting.")
        else:
            st.session_state.username = username.strip()

            # Signal old worker to stop (if any)
            if st.session_state.get("send_queue") is not None:
                try:
                    st.session_state.send_queue.put_nowait(None)
                except Exception:
                    pass

            # Optional: clear everything on reconnect
            # st.session_state.messages = []
            # st.session_state.seen_ids = set()

            start_ws_thread(host, int(port), st.session_state.username)

st.title("💬 Nodetalk Distributed Chat")
st.caption("Group chat on top of your replicated log (leader + followers).")

# 1) Message input – we DO NOT locally append; only send to server
user_text = None
if st.session_state.connected:
    user_text = st.chat_input("Type your message")
else:
    st.info("Not connected. Use the sidebar to connect to your Nodetalk node.")

if user_text:
    user_text = user_text.strip()
    if user_text:
        # Give the message a client-side id (server can reuse it or ignore it)
        msg_id = str(uuid.uuid4())
        outgoing = {
            "id": msg_id,
            "type": "chat",
            "from": st.session_state.username,
            "text": user_text,
        }

        # Send to server (background thread will pick this up)
        if "send_queue" in st.session_state:
            st.session_state.send_queue.put(outgoing)

# 2) Pull in any new messages from background worker (history + broadcasts)
drain_incoming()

# 3) Render chat history
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        msg_type = msg.get("type")

        if msg_type == "chat":
            sender = msg.get("from", "unknown")
            text = msg.get("text", "")

            # Style your own messages differently
            role = "user" if sender == st.session_state.username else "assistant"

            with st.chat_message(role):
                st.markdown(f"**{sender}**  \n{text}")

        elif msg_type == "system":
            # System / status messages
            st.markdown(
                f"<div style='text-align:center; color:gray; font-size:0.85rem;'>"
                f"{msg.get('text','')}"
                f"</div>",
                unsafe_allow_html=True,
            )

        else:
            # Fallback for any unusual messages
            st.markdown(
                f"<div style='text-align:center; color:#888; font-size:0.8rem;'>"
                f"[{msg_type}] {msg}"
                f"</div>",
                unsafe_allow_html=True,
            )

# 4) Auto-refresh loop so remote messages appear without interaction
if st.session_state.auto_refresh:
    # Short sleep to avoid hammering the server / CPU
    time.sleep(1.0)

    # Support both old and new Streamlit versions
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
