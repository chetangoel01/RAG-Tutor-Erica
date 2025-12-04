# Database Backup and Restore Scripts

This directory contains scripts to backup and restore your database state (MongoDB, Neo4j, and ChromaDB) so you don't need to re-fetch data from APIs every time you export or deploy the app.

## Quick Start

### Backup Databases

**Using Bash script:**
```bash
./scripts/backup_databases.sh
```

**Using Python script:**
```bash
python scripts/backup_databases.py
```

**Custom backup location:**
```bash
python scripts/backup_databases.py --output ./my_backup_folder
```

### Restore Databases

**Using Bash script:**
```bash
./scripts/restore_databases.sh ./data/exports/backup_20240101_120000
```

**Using Python script:**
```bash
python scripts/restore_databases.py ./data/exports/backup_20240101_120000
```

**Skip confirmation prompt:**
```bash
python scripts/restore_databases.py ./data/exports/backup_20240101_120000 --yes
```

## What Gets Backed Up?

### MongoDB
- All collections in the `erica` database:
  - `pages` - Web pages crawled from the course website
  - `resources` - PDFs, videos, images discovered
  - `chunks` - Text chunks extracted from documents
  - `extractions` - Concept and relationship extractions
  - `examples` - Code examples and explanations
  - `failures` - Failed crawl/download attempts

### Neo4j
- Knowledge graph data:
  - `Concept` nodes - AI/ML concepts extracted from content
  - `Resource` nodes - Links to source materials
  - `Example` nodes - Code examples and explanations
  - All relationships (PREREQUISITE, EXPLAINS, EXEMPLIFIES, etc.)

### ChromaDB
- Vector embeddings for semantic search
- Concept embeddings and metadata

## Backup Location

By default, backups are saved to:
```
./data/exports/backup_YYYYMMDD_HHMMSS/
```

Each backup contains:
- `mongodb_backup.tar.gz` - Compressed MongoDB dump
- `neo4j/` - Neo4j database dump files
- `chromadb/` - ChromaDB volume data
- `backup_manifest.txt` - Backup metadata and restore instructions

## Use Cases

### 1. Export/Deploy Your App

After you've crawled the website and built the knowledge graph:

```bash
# Create a backup
python scripts/backup_databases.py --output ./deployment_backup

# Include the backup folder in your deployment
# Then restore on the new system:
python scripts/restore_databases.py ./deployment_backup
```

### 2. Share Your Setup

If you want to share your pre-populated databases with others:

```bash
# Create a backup
./scripts/backup_databases.sh

# Share the backup folder (may be large!)
# Recipient restores:
./scripts/restore_databases.sh <backup_folder>
```

### 3. Version Control Your Data

Create backups at different stages:

```bash
# After ingestion
python scripts/backup_databases.py --output ./backups/after_ingestion

# After knowledge graph build
python scripts/backup_databases.py --output ./backups/after_kg_build

# After embedding
python scripts/backup_databases.py --output ./backups/after_embedding
```

## Requirements

- Docker and Docker Compose must be installed
- Containers must be accessible (running or can be started)
- Sufficient disk space for backups (can be several GB)

## Troubleshooting

### MongoDB Backup Fails
- Ensure MongoDB container is running: `docker ps | grep mongodb`
- Check MongoDB credentials match those in `docker-compose.yml`

### Neo4j Backup Fails
- Neo4j backup requires stopping the container temporarily
- If dump fails, the script will try a JSON export as fallback
- For large graphs, the backup may take several minutes

### ChromaDB Backup Fails
- ChromaDB data is stored in a Docker volume
- If volume is empty, backup will still succeed but warn you
- Ensure ChromaDB container has been used (embeddings created)

### Restore Overwrites Data
- ⚠️ **Warning**: Restore will overwrite existing database data
- Always backup current state before restoring if needed
- Use `--yes` flag to skip confirmation (useful for automation)

## File Sizes

Typical backup sizes:
- MongoDB: 50-500 MB (depends on crawled content)
- Neo4j: 10-100 MB (depends on knowledge graph size)
- ChromaDB: 100-500 MB (depends on number of embeddings)

Total: Usually 200 MB - 1 GB for a complete backup.

## Automation

You can automate backups in your deployment pipeline:

```bash
#!/bin/bash
# Example CI/CD script

# Backup before deployment
python scripts/backup_databases.py --output ./backups/pre_deploy_$(date +%Y%m%d)

# Deploy your app...

# Restore on new system
python scripts/restore_databases.py ./backups/pre_deploy_$(date +%Y%m%d) --yes
```

## Notes

- Backups are **not** incremental - each backup is a full snapshot
- Backups include all data, so they can be large
- Restore will **drop** existing data before restoring (MongoDB)
- Neo4j restore requires stopping the database temporarily
- ChromaDB restore requires stopping the service temporarily

## Alternative: Docker Volume Backups

For a simpler approach, you can also backup Docker volumes directly:

```bash
# Backup volumes
docker run --rm \
  -v erica_mongo_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/mongo_data.tar.gz -C /data .

docker run --rm \
  -v erica_neo4j_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/neo4j_data.tar.gz -C /data .

docker run --rm \
  -v erica_chroma_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/chroma_data.tar.gz -C /data .

# Restore volumes
docker run --rm \
  -v erica_mongo_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/mongo_data.tar.gz -C /data
```

However, the provided scripts handle this more safely with proper database export/import procedures.

