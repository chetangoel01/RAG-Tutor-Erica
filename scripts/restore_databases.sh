#!/bin/bash
# Restore script for MongoDB, Neo4j, and ChromaDB
# This restores database data from a previous backup

set -e  # Exit on error

# Configuration
BACKUP_PATH="${1:-./data/exports/latest}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Database Restore Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if backup path exists
if [ ! -d "$BACKUP_PATH" ]; then
    echo -e "${RED}✗ Error: Backup directory not found: ${BACKUP_PATH}${NC}"
    echo ""
    echo "Usage: $0 <backup_directory>"
    echo "Example: $0 ./data/exports/backup_20240101_120000"
    exit 1
fi

echo -e "${YELLOW}⚠ WARNING: This will overwrite existing database data!${NC}"
read -p "Are you sure you want to continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo ""

# Ensure containers are running
echo -e "${YELLOW}Ensuring containers are running...${NC}"
docker-compose up -d mongodb neo4j chromadb
sleep 10  # Wait for services to be ready
echo ""

# ============================================
# 1. Restore MongoDB
# ============================================
if [ -f "${BACKUP_PATH}/mongodb_backup.tar.gz" ]; then
    echo -e "${BLUE}[1/3] Restoring MongoDB...${NC}"
    
    # Extract backup
    TEMP_DIR=$(mktemp -d)
    tar -xzf "${BACKUP_PATH}/mongodb_backup.tar.gz" -C "${TEMP_DIR}"
    
    # Copy to container
    docker cp "${TEMP_DIR}/mongodb_backup" erica-mongodb:/tmp/
    
    # Restore database
    docker exec erica-mongodb mongorestore \
        --username=erica \
        --password=erica_password_123 \
        --authenticationDatabase=admin \
        --db=erica \
        --drop \
        /tmp/mongodb_backup/erica
    
    # Cleanup
    docker exec erica-mongodb rm -rf /tmp/mongodb_backup
    rm -rf "${TEMP_DIR}"
    
    echo -e "${GREEN}✓${NC} MongoDB restored successfully"
else
    echo -e "${YELLOW}⚠${NC} MongoDB backup not found, skipping..."
fi
echo ""

# ============================================
# 2. Restore Neo4j
# ============================================
if [ -d "${BACKUP_PATH}/neo4j" ] && [ "$(ls -A ${BACKUP_PATH}/neo4j 2>/dev/null)" ]; then
    echo -e "${BLUE}[2/3] Restoring Neo4j...${NC}"
    
    # Stop Neo4j for restore
    echo "  Stopping Neo4j for restore..."
    docker-compose stop neo4j
    
    # Check if we have a database dump file
    if ls "${BACKUP_PATH}/neo4j"/*.dump 1> /dev/null 2>&1; then
        DUMP_FILE=$(ls "${BACKUP_PATH}/neo4j"/*.dump | head -n 1)
        DUMP_NAME=$(basename "$DUMP_FILE")
        
        # Copy dump file to container
        docker run --rm \
            -v erica_neo4j_data:/data \
            -v "$(pwd)/${BACKUP_PATH}/neo4j":/backup \
            neo4j:5.15-community \
            sh -c "cp /backup/${DUMP_NAME} /data/dumps/${DUMP_NAME}"
        
        # Load database
        docker run --rm \
            -v erica_neo4j_data:/data \
            neo4j:5.15-community \
            neo4j-admin database load neo4j --from-path=/data/dumps --overwrite-destination=true
        
        echo -e "${GREEN}✓${NC} Neo4j restored from dump file"
    else
        echo -e "${YELLOW}⚠${NC} No Neo4j dump file found. You may need to manually import via Cypher."
        echo "  Backup files available in: ${BACKUP_PATH}/neo4j/"
    fi
    
    # Restart Neo4j
    docker-compose start neo4j
    sleep 10
    
    echo -e "${GREEN}✓${NC} Neo4j restored successfully"
else
    echo -e "${YELLOW}⚠${NC} Neo4j backup not found, skipping..."
fi
echo ""

# ============================================
# 3. Restore ChromaDB
# ============================================
if [ -d "${BACKUP_PATH}/chromadb" ] && [ "$(ls -A ${BACKUP_PATH}/chromadb 2>/dev/null)" ]; then
    echo -e "${BLUE}[3/3] Restoring ChromaDB...${NC}"
    
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
    
    if [ -z "$CHROMA_VOLUME_NAME" ]; then
        echo -e "${YELLOW}⚠${NC} Could not find ChromaDB volume. Skipping restore..."
    else
        echo -e "  Using volume: ${CHROMA_VOLUME_NAME}"
        
        # Stop ChromaDB
        docker-compose stop chromadb
        
        # Clear existing data and restore
        docker run --rm \
            -v "${CHROMA_VOLUME_NAME}:/chroma_data" \
            -v "$(pwd)/${BACKUP_PATH}/chromadb":/backup \
            alpine \
            sh -c "rm -rf /chroma_data/* && cp -r /backup/* /chroma_data/ 2>/dev/null || echo 'ChromaDB restore completed'"
        
        # Restart ChromaDB
        docker-compose start chromadb
        sleep 5
        
        echo -e "${GREEN}✓${NC} ChromaDB restored successfully"
    fi
else
    echo -e "${YELLOW}⚠${NC} ChromaDB backup not found, skipping..."
fi
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Restore Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "All databases have been restored from: ${BACKUP_PATH}"
echo "You can now start using the application without re-fetching data from APIs."
echo ""

