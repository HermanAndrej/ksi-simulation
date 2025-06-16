from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from hashlib import sha256
from datetime import datetime
import os
import json

app = FastAPI(title="KSI Simulation App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BATCH = []  # Current batch of file hashes
MERKLE_TREE = []  # Latest committed Merkle tree levels
COMMITS_FILE = "commits.json"

def load_commits():
    if os.path.exists(COMMITS_FILE):
        with open(COMMITS_FILE, "r") as f:
            return json.load(f)
    return []

def save_commits(commits):
    with open(COMMITS_FILE, "w") as f:
        json.dump(commits, f, indent=2)

# Load persistent commits on startup
COMMITTED_BATCHES = load_commits()

def hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()

def build_merkle_tree(hashes):
    if not hashes:
        return None, []
    tree_levels = [hashes]
    current_level = hashes
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else current_level[i]
            combined = sha256((left + right).encode()).hexdigest()
            next_level.append(combined)
        tree_levels.append(next_level)
        current_level = next_level
    return current_level[0], tree_levels

def generate_merkle_proof(tree_levels, index):
    proof = []
    for level in tree_levels[:-1]:  # Skip root level
        sibling_index = index + 1 if index % 2 == 0 else index - 1
        if sibling_index < len(level):
            proof.append(level[sibling_index])
        else:
            proof.append(level[index])  # Duplicate if no sibling
        index = index // 2
    return proof

@app.post("/submit")
async def submit_file(file: UploadFile = File(...)):
    content = await file.read()
    file_hash = hash_bytes(content)
    batch_position = len(BATCH)
    BATCH.append(file_hash)
    return {"hash": file_hash, "batch_position": batch_position}

@app.post("/commit")
def commit_batch():
    global BATCH, COMMITTED_BATCHES, MERKLE_TREE

    if not BATCH:
        raise HTTPException(status_code=400, detail="No files in batch to commit")

    # Copy BATCH so we keep data consistent during processing
    batch_to_commit = BATCH.copy()

    merkle_root, tree_levels = build_merkle_tree(batch_to_commit)
    timestamp = datetime.utcnow().isoformat() + "Z"
    chained_root = sha256((merkle_root + (COMMITTED_BATCHES[-1]["chained_root"] if COMMITTED_BATCHES else "")).encode()).hexdigest()
    batch_info = {
        "merkle_root": merkle_root,
        "chained_root": chained_root,
        "timestamp": timestamp,
        "batch_size": len(batch_to_commit),
        "tree_levels": tree_levels
    }

    COMMITTED_BATCHES.append(batch_info)
    save_commits(COMMITTED_BATCHES)

    # Clear the batch after commit
    BATCH.clear()

    MERKLE_TREE = tree_levels
    return {
        "merkle_root": merkle_root,
        "chained_root": chained_root,
        "timestamp": timestamp
    }

@app.get("/verify/{file_hash}")
def verify_hash(file_hash: str):
    global COMMITTED_BATCHES
    for batch_info in reversed(COMMITTED_BATCHES):
        level0 = batch_info.get("tree_levels", [[]])[0]
        if file_hash in level0:
            index = level0.index(file_hash)
            proof = generate_merkle_proof(batch_info["tree_levels"], index)
            return {
                "file_hash": file_hash,
                "batch_size": batch_info["batch_size"],
                "index": index,
                "merkle_root": batch_info["merkle_root"],
                "chained_root": batch_info["chained_root"],
                "previous_root": COMMITTED_BATCHES[-2]["merkle_root"] if len(COMMITTED_BATCHES) > 1 else None,
                "timestamp": batch_info["timestamp"],
                "proof": proof
            }
    raise HTTPException(status_code=404, detail="Hash not found in any committed batch")

@app.get("/verify/{file_hash}/token")
def download_proof_token(file_hash: str):
    global COMMITTED_BATCHES
    for batch_info in reversed(COMMITTED_BATCHES):
        level0 = batch_info.get("tree_levels", [[]])[0]
        if file_hash in level0:
            index = level0.index(file_hash)
            proof = generate_merkle_proof(batch_info["tree_levels"], index)
            token = {
                "file_hash": file_hash,
                "merkle_root": batch_info["merkle_root"],
                "proof": proof,
                "timestamp": batch_info["timestamp"],
                "index": index,
                "batch_size": batch_info["batch_size"]
            }
            return JSONResponse(content=token, media_type="application/json")
    raise HTTPException(status_code=404, detail="Proof token not found")

@app.get("/tree")
def merkle_tree_visualization():
    if not MERKLE_TREE:
        return HTMLResponse("<h2>No committed Merkle tree to show yet.</h2>")
    html = "<h2>Merkle Tree Visualization</h2><ul>"
    for level_num, level in enumerate(MERKLE_TREE):
        html += f"<li>Level {level_num}:<br>" + ", ".join(level) + "</li>"
    html += "</ul>"
    return HTMLResponse(html)

@app.get("/history")
def commit_history():
    return {
        "commits": [
            {
                "merkle_root": c["merkle_root"],
                "chained_root": c["chained_root"],
                "timestamp": c["timestamp"],
                "batch_size": c["batch_size"]
            }
            for c in COMMITTED_BATCHES
        ]
    }
