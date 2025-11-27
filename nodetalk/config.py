# nodetalk/config.py

# Static cluster configuration for the first prototype.
# Each node runs on its own UH VM.
NODES = {
    "A": "svm-11.cs.helsinki.fi",
    "B": "svm-11-2.cs.helsinki.fi",
    "C": "svm-11-3.cs.helsinki.fi",
}

# One common port for all nodes.
PORT = 9000
