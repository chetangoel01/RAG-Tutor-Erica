"""
Import extraction results from JSON back into MongoDB.

Run after Modal extraction completes:
    python import_extractions.py extractions.json
"""

from pymongo import MongoClient
import json
import os
from datetime import datetime

# Default MongoDB host: 'mongodb' for Docker, 'localhost' for host machine
MONGO_HOST = os.environ.get("MONGO_HOST", "mongodb")
DEFAULT_MONGO_URI = f"mongodb://erica:erica_password_123@{MONGO_HOST}:27017/"


def import_extractions(
    input_file: str,
    mongo_uri: str = None,
    db_name: str = "erica",
    collection: str = "extractions",
    clear_existing: bool = False,
):
    """
    Import extraction results into MongoDB.
    
    Args:
        input_file: JSON file with extraction results
        mongo_uri: MongoDB connection string
        db_name: Database name
        collection: Collection to store extractions
        clear_existing: Whether to clear existing extractions first
    """
    if mongo_uri is None:
        mongo_uri = DEFAULT_MONGO_URI
    print(f"Loading extractions from {input_file}...")
    with open(input_file) as f:
        extractions = json.load(f)
    
    print(f"Loaded {len(extractions)} extractions")
    
    # Connect to MongoDB
    print(f"Connecting to MongoDB...")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    if clear_existing:
        print(f"Clearing existing extractions...")
        db[collection].delete_many({})
    
    # Add metadata and insert
    docs = []
    for ext in extractions:
        doc = {
            "chunk_id": ext["chunk_id"],
            "source_url": ext.get("source_url", ""),
            "concepts": ext.get("concepts", []),
            "relations": ext.get("relations", []),
            "error": ext.get("error"),
            "raw_response": ext.get("raw_response", ""),
            "imported_at": datetime.utcnow(),
        }
        docs.append(doc)
    
    # Batch insert
    if docs:
        result = db[collection].insert_many(docs)
        print(f"Inserted {len(result.inserted_ids)} documents into '{collection}'")
    
    # Create indexes
    db[collection].create_index("chunk_id")
    db[collection].create_index("source_url")
    
    # Stats
    n_concepts = sum(len(e.get("concepts", [])) for e in extractions)
    n_relations = sum(len(e.get("relations", [])) for e in extractions)
    n_errors = sum(1 for e in extractions if e.get("error"))
    
    print(f"\nSummary:")
    print(f"  Total extractions: {len(extractions)}")
    print(f"  Total concepts:    {n_concepts}")
    print(f"  Total relations:   {n_relations}")
    print(f"  Errors:            {n_errors}")
    
    client.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Import extractions into MongoDB")
    parser.add_argument("input", help="Input JSON file with extractions")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI (defaults to MONGO_HOST env var)")
    parser.add_argument("--db", default="erica", help="Database name")
    parser.add_argument("--collection", default="extractions", help="Collection name")
    parser.add_argument("--clear", action="store_true", help="Clear existing extractions first")
    
    args = parser.parse_args()
    
    import_extractions(
        input_file=args.input,
        mongo_uri=args.mongo_uri,
        db_name=args.db,
        collection=args.collection,
        clear_existing=args.clear,
    )
