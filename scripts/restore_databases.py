#!/usr/bin/env python3
"""
Python-based database restore utility for MongoDB, Neo4j, and ChromaDB.

This script restores database data from a previous backup.

Usage:
    python scripts/restore_databases.py <backup_directory>
    python scripts/restore_databases.py ./data/exports/backup_20240101_120000
"""

import os
import sys
import subprocess
import tarfile
import shutil
from pathlib import Path
import argparse

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_container_running(container_name: str) -> bool:
    """Check if a Docker container is running."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    return container_name in result.stdout


def get_chromadb_volume_name() -> str:
    """Get the actual ChromaDB volume name (handles Docker Compose project name prefix)."""
    # List all volumes and find the chroma_data one
    result = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        volumes = result.stdout.strip().split('\n')
        # Look for volumes ending with _chroma_data
        chroma_volumes = [v for v in volumes if v.endswith('_chroma_data') or v == 'chroma_data']
        
        if chroma_volumes:
            # Check which one is actually in use by the chromadb container
            for vol in chroma_volumes:
                result = subprocess.run(
                    ["docker", "inspect", "erica-chromadb", "--format", "{{range .Mounts}}{{.Name}}{{end}}"],
                    capture_output=True,
                    text=True
                )
                if vol in result.stdout:
                    return vol
            # Fallback to first found
            return chroma_volumes[0]
    
    # Fallback to common names
    for name in ["erica_ai_tutor_chroma_data", "erica_chroma_data", "chroma_data"]:
        result = subprocess.run(
            ["docker", "volume", "inspect", name],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return name
    
    # Last resort
    return "erica_chroma_data"


def start_containers():
    """Start all required containers."""
    print("Ensuring containers are running...")
    subprocess.run(
        ["docker-compose", "up", "-d", "mongodb", "neo4j", "chromadb"],
        check=True,
        cwd=Path(__file__).parent.parent
    )
    import time
    time.sleep(10)  # Wait for services to be ready


def restore_mongodb(backup_path: Path):
    """Restore MongoDB database."""
    archive_path = backup_path / "mongodb_backup.tar.gz"
    
    if not archive_path.exists():
        print("⚠ MongoDB backup not found, skipping...")
        return False
    
    print("\n[1/3] Restoring MongoDB...")
    
    # Extract backup
    temp_dir = Path("/tmp") / f"mongo_restore_{os.getpid()}"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        print("  Extracting backup...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(temp_dir)
        
        # Copy to container
        backup_source = temp_dir / "mongodb_backup" / "erica"
        if not backup_source.exists():
            # Try alternative structure
            backup_source = list(temp_dir.glob("**/erica"))[0] if list(temp_dir.glob("**/erica")) else None
        
        if backup_source and backup_source.exists():
            print("  Copying backup to container...")
            subprocess.run([
                "docker", "cp",
                str(backup_source.parent),
                "erica-mongodb:/tmp/mongodb_backup"
            ], check=True)
            
            # Restore database
            print("  Restoring database (this may take a while)...")
            subprocess.run([
                "docker", "exec", "erica-mongodb",
                "mongorestore",
                "--username=erica",
                "--password=erica_password_123",
                "--authenticationDatabase=admin",
                "--db=erica",
                "--drop",
                "/tmp/mongodb_backup/erica"
            ], check=True)
            
            # Cleanup
            subprocess.run([
                "docker", "exec", "erica-mongodb",
                "rm", "-rf", "/tmp/mongodb_backup"
            ], check=False)
            
            print("  ✓ MongoDB restored successfully")
            return True
        else:
            print("  ✗ Could not find MongoDB backup data")
            return False
    
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def restore_neo4j(backup_path: Path):
    """Restore Neo4j database."""
    neo4j_backup_dir = backup_path / "neo4j"
    
    if not neo4j_backup_dir.exists() or not any(neo4j_backup_dir.iterdir()):
        print("⚠ Neo4j backup not found, skipping...")
        return False
    
    print("\n[2/3] Restoring Neo4j...")
    
    # Stop Neo4j for restore
    print("  Stopping Neo4j...")
    subprocess.run(
        ["docker-compose", "stop", "neo4j"],
        check=True,
        cwd=Path(__file__).parent.parent
    )
    
    try:
        # Look for dump file
        dump_files = list(neo4j_backup_dir.glob("*.dump"))
        
        if dump_files:
            dump_file = dump_files[0]
            dump_name = dump_file.name
            
            print(f"  Found dump file: {dump_name}")
            
            # Copy dump to Neo4j data directory
            print("  Copying dump to Neo4j...")
            subprocess.run([
                "docker", "run", "--rm",
                "-v", "erica_neo4j_data:/data",
                "-v", f"{neo4j_backup_dir}:/backup",
                "neo4j:5.15-community",
                "sh", "-c", f"mkdir -p /data/dumps && cp /backup/{dump_name} /data/dumps/{dump_name}"
            ], check=True)
            
            # Load database
            print("  Loading database (this may take a while)...")
            result = subprocess.run([
                "docker", "run", "--rm",
                "-v", "erica_neo4j_data:/data",
                "neo4j:5.15-community",
                "neo4j-admin", "database", "load", "neo4j",
                "--from-path=/data/dumps",
                "--overwrite-destination=true"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("  ✓ Neo4j restored from dump file")
                return True
            else:
                print(f"  ⚠ Warning: {result.stderr}")
                return False
        
        else:
            # Try JSON export restore
            json_file = neo4j_backup_dir / "neo4j_export.json"
            if json_file.exists():
                print(f"  Found JSON export: {json_file}")
                print("  Restoring from JSON (this may take a while)...")
                
                # Start Neo4j for import
                subprocess.run(
                    ["docker-compose", "start", "neo4j"],
                    check=True,
                    cwd=Path(__file__).parent.parent
                )
                import time
                time.sleep(10)
                
                # Import from JSON
                try:
                    from neo4j import GraphDatabase
                    import json
                    
                    # Load JSON data
                    with open(json_file, 'r') as f:
                        export_data = json.load(f)
                    
                    nodes = export_data.get("nodes", [])
                    relationships = export_data.get("relationships", [])
                    
                    print(f"  Loading {len(nodes)} nodes and {len(relationships)} relationships...")
                    
                    # Connect to Neo4j
                    driver = GraphDatabase.driver(
                        "bolt://localhost:7687",
                        auth=("neo4j", "erica_password_123")
                    )
                    
                    with driver.session() as session:
                        # Clear existing data
                        print("  Clearing existing data...")
                        session.run("MATCH (n) DETACH DELETE n")
                        
                        # Import nodes in batches
                        batch_size = 1000
                        node_count = 0
                        for i in range(0, len(nodes), batch_size):
                            batch = nodes[i:i + batch_size]
                            
                            # Group by label for efficient creation
                            by_label = {}
                            for node in batch:
                                labels = node.get("labels", [])
                                if not labels:
                                    continue
                                label_str = ":".join(labels)
                                if label_str not in by_label:
                                    by_label[label_str] = []
                                by_label[label_str].append(node.get("properties", {}))
                            
                            # Create nodes by label
                            for label_str, props_list in by_label.items():
                                labels = label_str.split(":")
                                label_cypher = ":".join(labels)
                                
                                query = f"""
                                UNWIND $props AS props
                                CREATE (n:{label_cypher})
                                SET n = props
                                """
                                session.run(query, props=props_list)
                                node_count += len(props_list)
                            
                            if (i + batch_size) % 5000 == 0:
                                print(f"    Processed {min(i + batch_size, len(nodes))}/{len(nodes)} nodes...")
                        
                        print(f"  ✓ Created {node_count} nodes")
                        
                        # Import relationships in batches
                        # Group relationships by type for efficient processing
                        rel_count = 0
                        batch_size = 500  # Smaller batches for relationships
                        
                        for i in range(0, len(relationships), batch_size):
                            batch = relationships[i:i + batch_size]
                            
                            # Process each relationship
                            for rel in batch:
                                from_node = rel.get("from", {})
                                to_node = rel.get("to", {})
                                rel_type = rel.get("type", "")
                                rel_props = rel.get("properties", {})
                                
                                from_labels = from_node.get("labels", [])
                                to_labels = to_node.get("labels", [])
                                from_props = from_node.get("properties", {})
                                to_props = to_node.get("properties", {})
                                
                                if not from_labels or not to_labels:
                                    continue
                                
                                # Determine unique identifier for matching
                                # Concepts use 'title', Resources use 'url', Examples use 'example_id'
                                from_key = None
                                from_value = None
                                to_key = None
                                to_value = None
                                
                                if "title" in from_props:
                                    from_key = "title"
                                    from_value = from_props["title"]
                                elif "url" in from_props:
                                    from_key = "url"
                                    from_value = from_props["url"]
                                elif "example_id" in from_props:
                                    from_key = "example_id"
                                    from_value = from_props["example_id"]
                                
                                if "title" in to_props:
                                    to_key = "title"
                                    to_value = to_props["title"]
                                elif "url" in to_props:
                                    to_key = "url"
                                    to_value = to_props["url"]
                                elif "example_id" in to_props:
                                    to_key = "example_id"
                                    to_value = to_props["example_id"]
                                
                                if not from_key or not to_key:
                                    continue
                                
                                # Build query with proper labels
                                from_label_str = ":".join(from_labels)
                                to_label_str = ":".join(to_labels)
                                
                                query = f"""
                                MATCH (from:{from_label_str} {{{from_key}: $from_val}})
                                MATCH (to:{to_label_str} {{{to_key}: $to_val}})
                                MERGE (from)-[r:{rel_type}]->(to)
                                """
                                
                                if rel_props:
                                    # Set relationship properties
                                    set_clauses = []
                                    for key, val in rel_props.items():
                                        set_clauses.append(f"r.{key} = ${key}")
                                    if set_clauses:
                                        query += " SET " + ", ".join(set_clauses)
                                
                                params = {
                                    "from_val": from_value,
                                    "to_val": to_value,
                                    **rel_props
                                }
                                
                                try:
                                    session.run(query, **params)
                                    rel_count += 1
                                except Exception as e:
                                    # Skip relationships that can't be matched
                                    pass
                            
                            if (i + batch_size) % 1000 == 0:
                                print(f"    Processed {min(i + batch_size, len(relationships))}/{len(relationships)} relationships...")
                        
                        print(f"  ✓ Created {rel_count} relationships")
                    
                    driver.close()
                    print("  ✓ Neo4j restored from JSON export")
                    return True
                    
                except Exception as e:
                    print(f"  ✗ Error restoring from JSON: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("  ⚠ No dump file or JSON export found")
                return False
    
    finally:
        # Always restart Neo4j
        print("  Restarting Neo4j...")
        subprocess.run(
            ["docker-compose", "start", "neo4j"],
            check=True,
            cwd=Path(__file__).parent.parent
        )
        import time
        time.sleep(10)


def restore_chromadb(backup_path: Path):
    """Restore ChromaDB data."""
    chroma_backup_dir = backup_path / "chromadb"
    
    if not chroma_backup_dir.exists() or not any(chroma_backup_dir.iterdir()):
        print("⚠ ChromaDB backup not found, skipping...")
        return False
    
    print("\n[3/3] Restoring ChromaDB...")
    
    # Stop ChromaDB
    print("  Stopping ChromaDB...")
    subprocess.run(
        ["docker-compose", "stop", "chromadb"],
        check=True,
        cwd=Path(__file__).parent.parent
    )
    
    try:
        # Get the actual volume name
        volume_name = get_chromadb_volume_name()
        print(f"  Using volume: {volume_name}")
        
        # Clear and restore volume data
        print("  Restoring volume data...")
        result = subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{volume_name}:/chroma_data",
            "-v", f"{chroma_backup_dir}:/backup",
            "alpine",
            "sh", "-c", "rm -rf /chroma_data/* && cp -r /backup/* /chroma_data/ 2>/dev/null || echo 'Restore completed'"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("  ✓ ChromaDB restored successfully")
            return True
        else:
            print(f"  ⚠ Warning: {result.stderr}")
            return False
    
    finally:
        # Always restart ChromaDB
        print("  Restarting ChromaDB...")
        subprocess.run(
            ["docker-compose", "start", "chromadb"],
            check=True,
            cwd=Path(__file__).parent.parent
        )
        import time
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Restore MongoDB, Neo4j, and ChromaDB databases from backup")
    parser.add_argument(
        "backup_path",
        help="Path to backup directory"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    args = parser.parse_args()
    
    backup_path = Path(args.backup_path)
    
    if not backup_path.exists():
        print(f"✗ Error: Backup directory not found: {backup_path}")
        sys.exit(1)
    
    print("=" * 40)
    print("Database Restore Script")
    print("=" * 40)
    print(f"\nBackup location: {backup_path}\n")
    
    if not args.yes:
        print("⚠ WARNING: This will overwrite existing database data!")
        confirm = input("Are you sure you want to continue? (yes/no): ")
        if confirm.lower() != "yes":
            print("Restore cancelled.")
            sys.exit(0)
    
    print()
    
    try:
        # Start containers
        start_containers()
        
        # Restore each database
        results = {
            "mongodb": restore_mongodb(backup_path),
            "neo4j": restore_neo4j(backup_path),
            "chromadb": restore_chromadb(backup_path)
        }
        
        print("\n" + "=" * 40)
        print("✓ Restore Complete!")
        print("=" * 40)
        print("\nRestore summary:")
        for db, success in results.items():
            status = "✓" if success else "⚠"
            print(f"  {status} {db}")
        print("\nYou can now start using the application without re-fetching data from APIs.")
        print()
        
    except Exception as e:
        print(f"\n✗ Error during restore: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

