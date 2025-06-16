from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from hashlib import sha256
from datetime import datetime
import json
import os

app = FastAPI(title="KSI Simulation App")

origins = [
    "http://localhost:8080"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_PATH = "storage/data.json"
BATCH = []
TREE = {}


# Hash file content
def hash_file_content(file_bytes: bytes) -> str:
    return sha256(file_bytes).hexdigest()


# Build Merkle Tree from list of hashes
def build_merkle_tree(hashes: list[str]) -> dict:
    if not hashes:
        return {"root": None, "layers": []}

    layers = [hashes]
    while len(layers[-1]) > 1:
        current_layer = layers[-1]
        next_layer = []
        for i in range(0, len(current_layer), 2):
            left = current_layer[i]
            right = current_layer[i + 1] if i + 1 < len(current_layer) else left
            combined = sha256((left + right).encode()).hexdigest()
            next_layer.append(combined)
        layers.append(next_layer)

    return {"root": layers[-1][0], "layers": layers}


# Submit file for hashing and batching
@app.post("/submit")
async def submit_file(file: UploadFile = File(...)):
    content = await file.read()
    file_hash = hash_file_content(content)
    BATCH.append(file_hash)
    return {"hash": file_hash, "batch_position": len(BATCH) - 1}


# Commit batch into Merkle Tree
@app.post("/commit")
def commit_batch():
    global TREE
    if not BATCH:
        raise HTTPException(status_code=400, detail="Batch is empty")

    TREE = build_merkle_tree(BATCH)
    timestamp = datetime.utcnow().isoformat()
    batch_data = {
        "timestamp": timestamp,
        "merkle_root": TREE["root"],
        "batch": BATCH,
        "tree": TREE
    }

    os.makedirs("storage", exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(batch_data, f, indent=2)

    BATCH.clear()
    return {"message": "Batch committed", "merkle_root": TREE["root"], "timestamp": timestamp}


# Verify hash inclusion
@app.get("/verify/{file_hash}")
def verify_hash(file_hash: str):
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="No committed batches found")

    with open(DATA_PATH, "r") as f:
        data = json.load(f)

    if file_hash not in data["batch"]:
        return JSONResponse(status_code=404, content={"valid": False, "reason": "Hash not found in last batch"})

    index = data["batch"].index(file_hash)
    proof = []
    layer = data["tree"]["layers"][0]

    for i in range(len(data["tree"]["layers"]) - 1):
        sibling_index = index ^ 1
        sibling = layer[sibling_index] if sibling_index < len(layer) else layer[index]
        proof.append(sibling)
        index = index // 2
        layer = data["tree"]["layers"][i + 1]

    return {
        "valid": True,
        "file_hash": file_hash,
        "merkle_root": data["merkle_root"],
        "proof": proof,
        "timestamp": data["timestamp"]
    }


# Graphical HTML visualization of current Merkle Tree
@app.get("/tree", response_class=HTMLResponse)
def show_tree():
    if not os.path.exists(DATA_PATH):
        return "<h3>No tree data found</h3>"

    with open(DATA_PATH, "r") as f:
        data = json.load(f)

    html = """
    <html>
    <head>
    <title>Merkle Tree Visualization</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #f7f7f7; padding: 20px; }}
        .layer {{ margin-bottom: 20px; }}
        .layer-title {{ font-weight: bold; margin-bottom: 10px; }}
        .hash-box {{
            display: inline-block;
            background: white;
            border: 1px solid #ccc;
            border-radius: 6px;
            padding: 8px;
            margin: 4px;
            font-family: monospace;
            font-size: 12px;
            max-width: 420px;
            overflow-wrap: break-word;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        }}
    </style>
    </head>
    <body>
    <h2>Merkle Tree Visualization</h2>
    <p><strong>Timestamp:</strong> {timestamp}</p>
    <p><strong>Merkle Root:</strong> {root}</p>
    <hr>
    """.format(timestamp=data['timestamp'], root=data['merkle_root'])

    for i, layer in enumerate(data['tree']['layers']):
        html += f"<div class='layer'><div class='layer-title'>Layer {i}</div>"
        for h in layer:
            html += f"<div class='hash-box'>{h}</div>"
        html += "</div>"

    html += "</body></html>"
    return html