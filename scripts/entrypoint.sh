#!/bin/bash
# Automated entrypoint: restore backup if needed, embed concepts if needed, start Streamlit

set -e

echo "=========================================="
echo "Erica AI Tutor - Automated Setup"
echo "=========================================="

# Step 1: Check if data exists, restore from backup if not
echo ""
echo "[1/3] Checking for existing data..."
python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')

from pymongo import MongoClient
from pathlib import Path
import subprocess

# Check MongoDB
mongo_client = MongoClient("mongodb://erica:erica_password_123@mongodb:27017/")
db = mongo_client["erica"]
concept_count = db.concepts.count_documents({})
mongo_client.close()

if concept_count > 0:
    print(f"  ✓ Found {concept_count} concepts in MongoDB")
    with open("/tmp/needs_restore.txt", "w") as f:
        f.write("false\n")
else:
    print("  ⚠ No data found in MongoDB")
    # Look for backups
    backup_dirs = []
    for base_path in ["/app/data/exports", "/app/data/backups"]:
        base = Path(base_path)
        if base.exists():
            backup_dirs.extend([d for d in base.iterdir() if d.is_dir() and (d / "backup_manifest.txt").exists()])
    
    if backup_dirs:
        # Use most recent backup
        backup_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        latest_backup = backup_dirs[0]
        print(f"  Found backup: {latest_backup}")
        print("  Restoring from backup...")
        
        try:
            result = subprocess.run(
                ["python3", "/app/scripts/restore_databases.py", str(latest_backup)],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            if "restored successfully" in result.stdout.lower() or result.returncode == 0:
                print("  ✓ Backup restored successfully")
                with open("/tmp/needs_restore.txt", "w") as f:
                    f.write("false\n")
            else:
                print(f"  ⚠ Backup restore had issues: {result.stderr[:200]}")
                with open("/tmp/needs_restore.txt", "w") as f:
                    f.write("false\n")  # Continue anyway
        except Exception as e:
            print(f"  ⚠ Could not restore backup: {e}")
            with open("/tmp/needs_restore.txt", "w") as f:
                f.write("false\n")
    else:
        print("  ⚠ No backups found. System will start but may need data loading.")
        with open("/tmp/needs_restore.txt", "w") as f:
            f.write("false\n")
PYTHON_SCRIPT

# Step 2: Embed concepts into ChromaDB if needed
echo ""
echo "[2/3] Checking ChromaDB embeddings..."
python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')

from pymongo import MongoClient
import chromadb

# Re-check MongoDB (in case we just restored)
mongo_client = MongoClient("mongodb://erica:erica_password_123@mongodb:27017/")
db = mongo_client["erica"]
concept_count = db.concepts.count_documents({})
mongo_client.close()

if concept_count == 0:
    print("  ⚠ No concepts in MongoDB. Skipping ChromaDB embedding.")
    print("     System will start but queries won't work until data is loaded.")
    sys.exit(0)

# Check ChromaDB
try:
    chroma_client = chromadb.HttpClient(host="chromadb", port=8000)
    try:
        collection = chroma_client.get_collection("concepts")
        chroma_count = collection.count()
        if chroma_count > 0:
            print(f"  ✓ ChromaDB has {chroma_count} embeddings. Ready!")
            sys.exit(0)
    except:
        pass  # Collection doesn't exist
    
    # Need to embed
    print(f"  Found {concept_count} concepts in MongoDB")
    print("  Embedding concepts into ChromaDB (this may take 1-2 minutes)...")
    
    from src.retrieval.concept_embeddings import ConceptEmbedder
    
    embedder = ConceptEmbedder(
        mongo_uri="mongodb://erica:erica_password_123@mongodb:27017/",
        chroma_host="chromadb",
        chroma_port=8000,
    )
    
    embedder.embed_all_concepts(clear_existing=True)
    stats = embedder.get_stats()
    print(f"  ✓ Embedded {stats.get('count', 0)} concepts into ChromaDB")
    embedder.close()
    
except Exception as e:
    print(f"  ⚠ Warning: Could not check/embed ChromaDB: {e}")
    print("     Continuing anyway - you can embed manually later if needed.")
PYTHON_SCRIPT

# Step 3: Start Streamlit
echo ""
echo "[3/3] Starting Streamlit app..."
echo "=========================================="
echo "✅ Setup complete! Erica AI Tutor is ready."
echo "Access the app at: http://localhost:8501"
echo "=========================================="
echo ""

# Start Streamlit
exec streamlit run src/app.py --server.port=8501 --server.address=0.0.0.0

