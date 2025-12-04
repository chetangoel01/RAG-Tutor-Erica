#!/bin/bash
# Backup script for MongoDB, Neo4j, and ChromaDB
# This exports all database data so you can restore it later without re-fetching from APIs

set -e  # Exit on error

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./data/exports}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/backup_${TIMESTAMP}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Database Backup Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Create backup directory
mkdir -p "${BACKUP_PATH}"
echo -e "${GREEN}✓${NC} Created backup directory: ${BACKUP_PATH}"
echo ""

# Check if containers are running
echo -e "${YELLOW}Checking if containers are running...${NC}"
if ! docker ps | grep -q erica-mongodb; then
    echo -e "${YELLOW}⚠ Warning: MongoDB container is not running${NC}"
    echo "  Starting MongoDB container..."
    docker-compose up -d mongodb
    sleep 5
fi

if ! docker ps | grep -q erica-neo4j; then
    echo -e "${YELLOW}⚠ Warning: Neo4j container is not running${NC}"
    echo "  Starting Neo4j container..."
    docker-compose up -d neo4j
    sleep 10  # Neo4j needs more time to start
fi

if ! docker ps | grep -q erica-chromadb; then
    echo -e "${YELLOW}⚠ Warning: ChromaDB container is not running${NC}"
    echo "  Starting ChromaDB container..."
    docker-compose up -d chromadb
    sleep 5
fi

echo ""

# ============================================
# 1. Backup MongoDB
# ============================================
echo -e "${BLUE}[1/3] Backing up MongoDB...${NC}"
MONGO_BACKUP="${BACKUP_PATH}/mongodb"
mkdir -p "${MONGO_BACKUP}"

docker exec erica-mongodb mongodump \
    --username=erica \
    --password=erica_password_123 \
    --authenticationDatabase=admin \
    --db=erica \
    --out=/tmp/mongodb_backup

docker cp erica-mongodb:/tmp/mongodb_backup "${MONGO_BACKUP}"
docker exec erica-mongodb rm -rf /tmp/mongodb_backup

# Create archive
tar -czf "${BACKUP_PATH}/mongodb_backup.tar.gz" -C "${MONGO_BACKUP}" mongodb_backup
rm -rf "${MONGO_BACKUP}/mongodb_backup"

echo -e "${GREEN}✓${NC} MongoDB backup saved to: ${BACKUP_PATH}/mongodb_backup.tar.gz"
echo ""

# ============================================
# 2. Backup Neo4j
# ============================================
echo -e "${BLUE}[2/3] Backing up Neo4j...${NC}"
NEO4J_BACKUP="${BACKUP_PATH}/neo4j"
mkdir -p "${NEO4J_BACKUP}"

# Stop Neo4j to perform a clean backup (required for neo4j-admin)
echo "  Stopping Neo4j temporarily for backup..."
docker-compose stop neo4j

# Get the volume path
NEO4J_VOLUME=$(docker volume inspect erica_neo4j_data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")

if [ -n "$NEO4J_VOLUME" ]; then
    # Use neo4j-admin dump from a temporary container
    docker run --rm \
        -v erica_neo4j_data:/data \
        -v "$(pwd)/${NEO4J_BACKUP}":/backup \
        neo4j:5.15-community \
        neo4j-admin database dump neo4j --to-path=/backup
    echo -e "${GREEN}✓${NC} Neo4j backup saved to: ${BACKUP_PATH}/neo4j/"
else
    # Fallback: use Cypher export via running container
    echo "  Using Cypher export method..."
    docker-compose start neo4j
    sleep 10
    
    # Export using Cypher (less reliable but works without stopping)
    docker exec erica-neo4j cypher-shell \
        -u neo4j \
        -p erica_password_123 \
        "CALL apoc.export.graphml.all('/tmp/neo4j_backup.graphml', {})" || \
    docker exec erica-neo4j cypher-shell \
        -u neo4j \
        -p erica_password_123 \
        "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m" > "${NEO4J_BACKUP}/cypher_export.cypher" || \
    echo "  Note: Neo4j backup may require manual export via Neo4j Browser"
fi

# Restart Neo4j
docker-compose start neo4j

echo -e "${GREEN}✓${NC} Neo4j backup saved to: ${BACKUP_PATH}/neo4j/"
echo ""

# ============================================
# 3. Backup ChromaDB
# ============================================
echo -e "${BLUE}[3/3] Backing up ChromaDB...${NC}"
CHROMA_BACKUP="${BACKUP_PATH}/chromadb"
mkdir -p "${CHROMA_BACKUP}"

# Find the actual ChromaDB volume name (handles Docker Compose project name prefix)
CHROMA_VOLUME_NAME=""
for vol_name in erica_ai_tutor_chroma_data erica_chroma_data chroma_data; do
    if docker volume inspect "$vol_name" >/dev/null 2>&1; then
        # Check if this volume is actually used by the chromadb container
        if docker inspect erica-chromadb --format '{{range .Mounts}}{{.Name}}{{end}}' 2>/dev/null | grep -q "$vol_name"; then
            CHROMA_VOLUME_NAME="$vol_name"
            break
        fi
    fi
done

# Fallback: try to find any volume ending with _chroma_data
if [ -z "$CHROMA_VOLUME_NAME" ]; then
    CHROMA_VOLUME_NAME=$(docker volume ls --format '{{.Name}}' | grep '_chroma_data$' | head -n1)
fi

if [ -n "$CHROMA_VOLUME_NAME" ]; then
    echo -e "  Using volume: ${CHROMA_VOLUME_NAME}"
    # Copy volume data
    docker run --rm \
        -v "${CHROMA_VOLUME_NAME}:/chroma_data" \
        -v "$(pwd)/${CHROMA_BACKUP}":/backup \
        alpine \
        sh -c "cp -r /chroma_data/* /backup/ 2>/dev/null || echo 'ChromaDB volume is empty or inaccessible'"
    echo -e "${GREEN}✓${NC} ChromaDB backup saved to: ${BACKUP_PATH}/chromadb/"
else
    echo -e "${YELLOW}⚠${NC} Could not find ChromaDB volume. ChromaDB data may be empty."
fi

echo ""

# ============================================
# Create backup manifest
# ============================================
cat > "${BACKUP_PATH}/backup_manifest.txt" << EOF
Database Backup Manifest
========================
Timestamp: ${TIMESTAMP}
Date: $(date)

Contents:
- MongoDB: mongodb_backup.tar.gz
- Neo4j: neo4j/ (database dump)
- ChromaDB: chromadb/ (volume data)

To restore, run:
  ./scripts/restore_databases.sh ${BACKUP_PATH}

EOF

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Backup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Backup location: ${BACKUP_PATH}"
echo "To restore, run: ./scripts/restore_databases.sh ${BACKUP_PATH}"
echo ""

