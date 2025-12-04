"""
Import examples from extractions.json into MongoDB and Neo4j.

Usage:

    python -m src.graph.import_examples --json extractions.json

"""

import json
import argparse
import hashlib
import os
from pymongo import MongoClient, UpdateOne
from neo4j import GraphDatabase

# Default MongoDB host: 'mongodb' for Docker, 'localhost' for host machine
MONGO_HOST = os.environ.get("MONGO_HOST", "mongodb")
DEFAULT_MONGO_URI = f"mongodb://erica:erica_password_123@{MONGO_HOST}:27017/"

# Default Neo4j host: 'neo4j' for Docker, 'localhost' for host machine
NEO4J_HOST = os.environ.get("NEO4J_HOST", "neo4j")
DEFAULT_NEO4J_URI = f"bolt://{NEO4J_HOST}:7687"


def generate_example_id(text: str, concept: str) -> str:
    """Generate a unique ID for an example."""
    content = f"{text}:{concept}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def import_examples(
    json_file: str,
    mongo_uri: str = None,
    neo4j_uri: str = None,
    neo4j_user: str = "neo4j",
    neo4j_password: str = "erica_password_123",
    db_name: str = "erica",
    clear_existing: bool = False,
):
    """
    Import examples into MongoDB and create Example nodes in Neo4j.
    """
    # Set default URIs if not provided
    if mongo_uri is None:
        mongo_uri = DEFAULT_MONGO_URI
    if neo4j_uri is None:
        neo4j_uri = DEFAULT_NEO4J_URI
    
    # Load extractions
    print(f"Loading {json_file}...")
    with open(json_file) as f:
        extractions = json.load(f)
    
    # Collect all examples with metadata
    all_examples = []
    for ext in extractions:
        chunk_id = ext.get("chunk_id", "")
        source_url = ext.get("source_url", "")
        
        for example in ext.get("examples", []):
            if not example.get("text") or not example.get("concept"):
                continue
                
            example_id = generate_example_id(example["text"], example["concept"])
            all_examples.append({
                "example_id": example_id,
                "text": example["text"],
                "concept": example["concept"],
                "example_type": example.get("example_type", "unknown"),
                "chunk_id": chunk_id,
                "source_url": source_url,
            })
    
    print(f"Found {len(all_examples)} examples")
    
    # Deduplicate examples by example_id (keep first occurrence)
    seen_ids = {}
    unique_examples = []
    for ex in all_examples:
        ex_id = ex["example_id"]
        if ex_id not in seen_ids:
            seen_ids[ex_id] = True
            unique_examples.append(ex)
    
    if len(all_examples) != len(unique_examples):
        print(f"  Deduplicated to {len(unique_examples)} unique examples (removed {len(all_examples) - len(unique_examples)} duplicates)")
    
    # --- MongoDB: Store examples in their own collection ---
    print("\nImporting to MongoDB...")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    # Create examples collection
    if clear_existing:
        print("  Clearing existing examples...")
        db.examples.delete_many({})
    
    # Create indexes first (if collection is empty or cleared)
    try:
        db.examples.create_index("example_id", unique=True)
        db.examples.create_index("concept")
        db.examples.create_index("example_type")
    except Exception as e:
        # Indexes might already exist, that's okay
        print(f"  Note: Some indexes may already exist: {e}")
    
    if unique_examples:
        # Use bulk_write with upsert to handle any remaining duplicates gracefully
        operations = [
            UpdateOne(
                {"example_id": ex["example_id"]},
                {"$set": ex},
                upsert=True
            )
            for ex in unique_examples
        ]
        result = db.examples.bulk_write(operations, ordered=False)
        print(f"  Upserted {result.upserted_count + result.modified_count} examples into MongoDB")
        if result.upserted_count > 0:
            print(f"    - {result.upserted_count} new examples")
        if result.modified_count > 0:
            print(f"    - {result.modified_count} updated examples")
    
    # Also update extractions to include examples field
    print("  Updating extractions collection with examples...")
    for ext in extractions:
        if ext.get("examples"):
            db.extractions.update_one(
                {"chunk_id": ext["chunk_id"]},
                {"$set": {"examples": ext["examples"]}}
            )
    
    client.close()
    
    # --- Neo4j: Create Example nodes and EXEMPLIFIES edges ---
    print("\nImporting to Neo4j...")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    with driver.session() as session:
        # Create constraint for Example nodes
        try:
            session.run("""
                CREATE CONSTRAINT example_id IF NOT EXISTS
                FOR (e:Example) REQUIRE e.example_id IS UNIQUE
            """)
        except Exception as e:
            print(f"  Constraint may already exist: {e}")
        
        # Clear existing examples if requested
        if clear_existing:
            print("  Clearing existing Example nodes and EXEMPLIFIES edges...")
            session.run("MATCH (e:Example) DETACH DELETE e")
        
        # Batch import examples
        print("  Creating Example nodes and EXEMPLIFIES edges...")
        
        # Process in batches
        batch_size = 500
        created = 0
        linked = 0
        
        for i in range(0, len(unique_examples), batch_size):
            batch = unique_examples[i:i + batch_size]
            
            result = session.run("""
                UNWIND $examples AS ex
                MERGE (e:Example {example_id: ex.example_id})
                SET e.text = ex.text,
                    e.example_type = ex.example_type,
                    e.chunk_id = ex.chunk_id,
                    e.source_url = ex.source_url
                WITH e, ex
                OPTIONAL MATCH (c:Concept)
                WHERE c.title = ex.concept 
                   OR toLower(trim(c.title)) = toLower(trim(ex.concept))
                   OR ex.concept IN c.aliases
                   OR ANY(alias IN c.aliases WHERE alias IS NOT NULL AND toLower(trim(alias)) = toLower(trim(ex.concept)))
                WITH e, ex, c
                WHERE c IS NOT NULL
                MERGE (e)-[:EXEMPLIFIES]->(c)
                RETURN count(DISTINCT e) as examples_created, count(*) as links_created
            """, examples=batch)
            
            record = result.single()
            created += record["examples_created"]
            linked += record["links_created"]
            
            print(f"    Processed {min(i + batch_size, len(unique_examples))}/{len(unique_examples)}")
        
        # Count unlinked examples and get sample missing concepts
        unlinked_result = session.run("""
            MATCH (e:Example)
            WHERE NOT (e)-[:EXEMPLIFIES]->(:Concept)
            RETURN e.concept AS concept, count(e) as count
            ORDER BY count DESC
            LIMIT 20
        """)
        unlinked_examples = list(unlinked_result)
        total_unlinked = sum(r["count"] for r in unlinked_examples)
        
        print(f"\n  Example nodes created: {created}")
        print(f"  EXEMPLIFIES edges created: {linked}")
        if total_unlinked > 0:
            print(f"  Examples without matching concept: {total_unlinked}")
            if unlinked_examples:
                print(f"\n  Top unmatched concepts (showing up to 20):")
                for r in unlinked_examples[:10]:
                    print(f"    - '{r['concept']}': {r['count']} examples")
    
    driver.close()
    
    # --- Summary ---
    print("\n" + "=" * 50)
    print("IMPORT COMPLETE")
    print("=" * 50)
    
    # Show example types breakdown
    type_counts = {}
    for ex in unique_examples:
        t = ex["example_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    
    print("\nExamples by type:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import examples into MongoDB and Neo4j")
    parser.add_argument("--json", default="extractions.json", help="Path to extractions JSON")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI (defaults to MONGO_HOST env var)")
    parser.add_argument("--neo4j-uri", default=None, help="Neo4j URI (defaults to NEO4J_HOST env var)")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="erica_password_123")
    parser.add_argument("--db", default="erica")
    parser.add_argument("--clear", action="store_true", help="Clear existing examples first")
    
    args = parser.parse_args()
    
    import_examples(
        json_file=args.json,
        mongo_uri=args.mongo_uri,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        db_name=args.db,
        clear_existing=args.clear,
    )

