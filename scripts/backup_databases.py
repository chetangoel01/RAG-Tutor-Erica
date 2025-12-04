#!/usr/bin/env python3
"""
Python-based database backup utility for MongoDB, Neo4j, and ChromaDB.

This script exports all database data so you can restore it later without
re-fetching from APIs.

Usage:
    python scripts/backup_databases.py
    python scripts/backup_databases.py --output ./my_backup
"""

import os
import sys
import subprocess
import tarfile
import shutil
from pathlib import Path
from datetime import datetime
import argparse

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import MongoClient
from neo4j import GraphDatabase


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
    # Try to get project name from docker-compose
    try:
        result = subprocess.run(
            ["docker-compose", "config", "--services"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        if result.returncode == 0:
            # Get project name
            result = subprocess.run(
                ["docker-compose", "config", "--volumes"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent
            )
    except:
        pass
    
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
            for vol in chroma_volumes:
                result = subprocess.run(
                    ["docker", "inspect", "erica-chromadb", "--format", "{{range .Mounts}}{{.Name}}{{end}}"],
                    capture_output=True,
                    text=True
                )
                if vol in result.stdout:
                    return vol
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


def start_container(service_name: str):
    """Start a Docker Compose service."""
    print(f"  Starting {service_name} container...")
    subprocess.run(
        ["docker-compose", "up", "-d", service_name],
        check=True,
        cwd=Path(__file__).parent.parent
    )
    if service_name == "neo4j":
        import time
        time.sleep(10)  # Neo4j needs time to start
    else:
        import time
        time.sleep(5)


def backup_mongodb(backup_path: Path):
    """Backup MongoDB database."""
    print("\n[1/3] Backing up MongoDB...")
    
    if not check_container_running("erica-mongodb"):
        start_container("mongodb")
    
    mongo_backup_dir = backup_path / "mongodb"
    mongo_backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Use mongodump via docker exec
    print("  Running mongodump...")
    subprocess.run([
        "docker", "exec", "erica-mongodb",
        "mongodump",
        "--username=erica",
        "--password=erica_password_123",
        "--authenticationDatabase=admin",
        "--db=erica",
        "--out=/tmp/mongodb_backup"
    ], check=True)
    
    # Copy backup from container
    print("  Copying backup from container...")
    subprocess.run([
        "docker", "cp",
        "erica-mongodb:/tmp/mongodb_backup",
        str(mongo_backup_dir)
    ], check=True)
    
    # Cleanup container temp
    subprocess.run([
        "docker", "exec", "erica-mongodb",
        "rm", "-rf", "/tmp/mongodb_backup"
    ], check=False)
    
    # Create compressed archive
    print("  Creating archive...")
    archive_path = backup_path / "mongodb_backup.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(mongo_backup_dir / "mongodb_backup", arcname="mongodb_backup")
    
    # Remove uncompressed backup
    shutil.rmtree(mongo_backup_dir / "mongodb_backup", ignore_errors=True)
    
    print(f"  ✓ MongoDB backup saved to: {archive_path}")
    return archive_path


def backup_neo4j(backup_path: Path):
    """Backup Neo4j database."""
    print("\n[2/3] Backing up Neo4j...")
    
    if not check_container_running("erica-neo4j"):
        start_container("neo4j")
    
    neo4j_backup_dir = backup_path / "neo4j"
    neo4j_backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Stop Neo4j for clean backup
    print("  Stopping Neo4j for backup...")
    subprocess.run(
        ["docker-compose", "stop", "neo4j"],
        check=True,
        cwd=Path(__file__).parent.parent
    )
    
    try:
        # Use neo4j-admin dump
        print("  Creating database dump...")
        result = subprocess.run([
            "docker", "run", "--rm",
            "-v", "erica_neo4j_data:/data",
            "-v", f"{neo4j_backup_dir}:/backup",
            "neo4j:5.15-community",
            "neo4j-admin", "database", "dump", "neo4j", "--to-path=/backup"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"  ✓ Neo4j dump created in: {neo4j_backup_dir}")
        else:
            print(f"  ⚠ Warning: {result.stderr}")
            print("  Trying alternative export method...")
            
            # Alternative: Export via Cypher
            subprocess.run(
                ["docker-compose", "start", "neo4j"],
                check=True,
                cwd=Path(__file__).parent.parent
            )
            import time
            time.sleep(10)
            
            # Export all nodes and relationships
            driver = GraphDatabase.driver(
                "bolt://localhost:7687",
                auth=("neo4j", "erica_password_123")
            )
            
            with driver.session() as session:
                # Export nodes
                nodes_query = """
                MATCH (n)
                RETURN labels(n) as labels, properties(n) as props
                """
                nodes = list(session.run(nodes_query))
                
                # Export relationships
                rels_query = """
                MATCH (a)-[r]->(b)
                RETURN labels(a) as from_labels, properties(a) as from_props,
                       type(r) as rel_type, properties(r) as rel_props,
                       labels(b) as to_labels, properties(b) as to_props
                """
                rels = list(session.run(rels_query))
            
            driver.close()
            
            # Save to JSON
            import json
            export_data = {
                "nodes": [{"labels": list(r["labels"]), "properties": dict(r["props"])} for r in nodes],
                "relationships": [
                    {
                        "from": {"labels": list(r["from_labels"]), "properties": dict(r["from_props"])},
                        "type": r["rel_type"],
                        "properties": dict(r["rel_props"]),
                        "to": {"labels": list(r["to_labels"]), "properties": dict(r["to_props"])}
                    }
                    for r in rels
                ]
            }
            
            export_file = neo4j_backup_dir / "neo4j_export.json"
            with open(export_file, "w") as f:
                json.dump(export_data, f, indent=2, default=str)
            
            print(f"  ✓ Neo4j export saved to: {export_file}")
    
    finally:
        # Always restart Neo4j
        print("  Restarting Neo4j...")
        subprocess.run(
            ["docker-compose", "start", "neo4j"],
            check=True,
            cwd=Path(__file__).parent.parent
        )
    
    return neo4j_backup_dir


def backup_chromadb(backup_path: Path):
    """Backup ChromaDB data."""
    print("\n[3/3] Backing up ChromaDB...")
    
    if not check_container_running("erica-chromadb"):
        start_container("chromadb")
    
    chroma_backup_dir = backup_path / "chromadb"
    chroma_backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Get the actual volume name
    volume_name = get_chromadb_volume_name()
    print(f"  Using volume: {volume_name}")
    
    # Copy volume data
    print("  Copying ChromaDB volume data...")
    result = subprocess.run([
        "docker", "run", "--rm",
        "-v", f"{volume_name}:/chroma_data",
        "-v", f"{chroma_backup_dir}:/backup",
        "alpine",
        "sh", "-c", "cp -r /chroma_data/* /backup/ 2>/dev/null || echo 'Volume may be empty'"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"  ✓ ChromaDB backup saved to: {chroma_backup_dir}")
    else:
        print(f"  ⚠ Warning: {result.stderr}")
    
    return chroma_backup_dir


def create_manifest(backup_path: Path):
    """Create a manifest file describing the backup."""
    manifest_path = backup_path / "backup_manifest.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(manifest_path, "w") as f:
        f.write("Database Backup Manifest\n")
        f.write("=" * 40 + "\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("Contents:\n")
        f.write("- MongoDB: mongodb_backup.tar.gz\n")
        f.write("- Neo4j: neo4j/ (database dump or JSON export)\n")
        f.write("- ChromaDB: chromadb/ (volume data)\n\n")
        f.write("To restore, run:\n")
        f.write(f"  python scripts/restore_databases.py {backup_path}\n")
        f.write("  or\n")
        f.write(f"  ./scripts/restore_databases.sh {backup_path}\n")
    
    print(f"\n✓ Manifest created: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="Backup MongoDB, Neo4j, and ChromaDB databases")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory for backup (default: ./data/exports/backup_TIMESTAMP)"
    )
    
    args = parser.parse_args()
    
    # Determine backup path
    if args.output:
        backup_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(__file__).parent.parent / "data" / "exports" / f"backup_{timestamp}"
    
    backup_path.mkdir(parents=True, exist_ok=True)
    
    print("=" * 40)
    print("Database Backup Script")
    print("=" * 40)
    print(f"\nBackup location: {backup_path}\n")
    
    try:
        # Backup each database
        backup_mongodb(backup_path)
        backup_neo4j(backup_path)
        backup_chromadb(backup_path)
        
        # Create manifest
        create_manifest(backup_path)
        
        print("\n" + "=" * 40)
        print("✓ Backup Complete!")
        print("=" * 40)
        print(f"\nBackup saved to: {backup_path}")
        print(f"\nTo restore, run:")
        print(f"  python scripts/restore_databases.py {backup_path}")
        print(f"  or")
        print(f"  ./scripts/restore_databases.sh {backup_path}")
        print()
        
    except Exception as e:
        print(f"\n✗ Error during backup: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

