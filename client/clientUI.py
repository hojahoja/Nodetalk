import asyncio
import json
import threading
import queue
import time
import uuid

import streamlit as st
import websockets

# Default server the UI talks to when it first opens
SERVER_HOST = "localhost"
DEFAULT_PORT = 9000


# Background task that keeps the chat connection alive
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
            # Let the server know who just joined
            await websocket.send(json.dumps({
                "type": "join",
                "from": username,
            }))
            incoming_q.put({
                "type": "system",
                "text": f"Connected to {uri} as {username}",
            })

            # Ships anything the user writes to the server
            async def sender():
                while True:
                    try:
                        msg = send_q.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue

                    if msg is None:
                        # Stop once the UI asks us to exit
                        break

                    await websocket.send(json.dumps(msg))

            # Collects everything the server sends back
            async def receiver():
                async for raw in websocket:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = {"type": "system", "text": raw}
                    incoming_q.put(msg)

            # Keep sending and receiving running together
            await asyncio.gather(sender(), receiver())

    except Exception as e:
        # Report any connection trouble back to the UI
        incoming_q.put({
            "type": "system",
            "text": f"Connection error: {e}",
        })


# Starts the background worker thread so Streamlit stays responsive
def start_ws_thread(host: str, port: int, username: str) -> None:
    # Make sure the queues exist before launching the worker
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


# Pulls buffered messages into the visible chat log
def drain_incoming() -> None:
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
                # Ignore duplicates we have already shown
                if msg_id in st.session_state.seen_ids:
                    continue
                st.session_state.seen_ids.add(msg_id)

        st.session_state.messages.append(msg)

# Basic page setup for Streamlit
st.set_page_config(
    page_title="Nodetalk Chat",
    page_icon="💬",
    layout="centered",
)

# Prepare session storage for this browser tab
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
    # Auto-refresh starts enabled so new messages appear on their own
    st.session_state.auto_refresh = True

# Sidebar controls for joining a server
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

            # Ask any previous worker to shut down
            if st.session_state.get("send_queue") is not None:
                try:
                    st.session_state.send_queue.put_nowait(None)
                except Exception:
                    pass

            start_ws_thread(host, int(port), st.session_state.username)

st.title("💬 Nodetalk Distributed Chat")
st.caption("Group chat on top of your replicated log (leader + followers).")

# Message input is only active when connected
user_text = None
if st.session_state.connected:
    user_text = st.chat_input("Type your message")
else:
    st.info("Not connected. Use the sidebar to connect to your Nodetalk node.")

if user_text:
    user_text = user_text.strip()
    if user_text:
        # Tag the outgoing message with a simple id
        msg_id = str(uuid.uuid4())
        outgoing = {
            "id": msg_id,
            "type": "chat",
            "from": st.session_state.username,
            "text": user_text,
        }

        # Hand the message to the background worker
        if "send_queue" in st.session_state:
            st.session_state.send_queue.put(outgoing)

# Pull in fresh messages from the background worker before rendering
drain_incoming()

# Show the full conversation so far
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        msg_type = msg.get("type")

        if msg_type == "chat":
            sender = msg.get("from", "unknown")
            text = msg.get("text", "")

            # Highlight the local user's own lines
            role = "user" if sender == st.session_state.username else "assistant"

            with st.chat_message(role):
                st.markdown(f"**{sender}**  \n{text}")

        elif msg_type == "system":
            # Center short status notes
            st.markdown(
                f"<div style='text-align:center; color:gray; font-size:0.85rem;'>"
                f"{msg.get('text','')}"
                f"</div>",
                unsafe_allow_html=True,
            )

        else:
            # Show anything unexpected without crashing
            st.markdown(
                f"<div style='text-align:center; color:#888; font-size:0.8rem;'>"
                f"[{msg_type}] {msg}"
                f"</div>",
                unsafe_allow_html=True,
            )

# Refresh automatically so remote messages appear on their own
if st.session_state.auto_refresh:
    # Pause briefly so we do not hog the CPU
    time.sleep(1.0)

    # Use whichever rerun API this Streamlit build offers
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
