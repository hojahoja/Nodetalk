# nodetalk/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load the port number from an environmental
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
_env_port = os.environ.get("NT_PORT")

# Static cluster configuration for the first prototype.
# Each node runs on its own UH VM.
NODES = {
    "A": "svm-11.cs.helsinki.fi",
    "B": "svm-11-2.cs.helsinki.fi",
    "C": "svm-11-3.cs.helsinki.fi",
}

# One common port for all nodes. Load the port number from the environmental
# variable or default to 9000
PORT = int(_env_port) if _env_port and _env_port.isdigit() else 9000
