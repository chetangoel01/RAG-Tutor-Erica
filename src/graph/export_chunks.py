"""
Export chunks from MongoDB to JSON for Modal processing.

Run this locally before running Modal extraction:
    python export_chunks.py

This creates chunks.json which can be uploaded to Modal.
"""

from pymongo import MongoClient
import json
import os
from datetime import datetime

# Default MongoDB host: 'mongodb' for Docker, 'localhost' for host machine
MONGO_HOST = os.environ.get("MONGO_HOST", "mongodb")
DEFAULT_MONGO_URI = f"mongodb://erica:erica_password_123@{MONGO_HOST}:27017/"


def export_chunks(
    mongo_uri: str = None,
    db_name: str = "erica",
    output_file: str = "chunks.json",
    limit: int = None,
):
    """
    Export chunks from MongoDB to JSON file.
    
    Args:
        mongo_uri: MongoDB connection string
        db_name: Database name
        output_file: Output JSON file path
        limit: Optional limit on number of chunks
    """
    if mongo_uri is None:
        mongo_uri = DEFAULT_MONGO_URI
    print(f"Connecting to MongoDB...")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    # Count chunks
    total = db.chunks.count_documents({})
    print(f"Found {total} chunks in MongoDB")
    
    # Query chunks
    query = {}
    cursor = db.chunks.find(query)
    if limit:
        cursor = cursor.limit(limit)
        print(f"Limiting to {limit} chunks")
    
    # Convert to list
    chunks = []
    for doc in cursor:
        chunk = {
            "chunk_id": doc.get("chunk_id", str(doc["_id"])),
            "text": doc.get("text", ""),
            "source_url": doc.get("source_url", ""),
            "source_type": doc.get("source_type", "unknown"),
            "source_title": doc.get("source_title", ""),
            "chunk_index": doc.get("chunk_index", 0),
            "token_count": doc.get("token_count", 0),
        }
        chunks.append(chunk)
    
    print(f"Exported {len(chunks)} chunks")
    
    # Save to JSON
    with open(output_file, "w") as f:
        json.dump(chunks, f, indent=2)
    
    print(f"Saved to {output_file}")
    
    # Stats
    by_type = {}
    total_tokens = 0
    for c in chunks:
        t = c["source_type"]
        by_type[t] = by_type.get(t, 0) + 1
        total_tokens += c.get("token_count", 0)
    
    print(f"\nBy source type:")
    for t, count in sorted(by_type.items()):
        print(f"  {t}: {count}")
    print(f"\nTotal tokens: {total_tokens:,}")
    
    client.close()
    return chunks


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Export chunks from MongoDB to JSON")
    parser.add_argument("--output", "-o", default="chunks.json", help="Output JSON file")
    parser.add_argument("--limit", "-l", type=int, help="Limit number of chunks")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI (defaults to MONGO_HOST env var)")
    parser.add_argument("--db", default="erica", help="Database name")
    
    args = parser.parse_args()
    
    export_chunks(
        mongo_uri=args.mongo_uri,
        db_name=args.db,
        output_file=args.output,
        limit=args.limit,
    )
