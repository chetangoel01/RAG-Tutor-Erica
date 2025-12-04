"""
Storage operations for MongoDB and filesystem.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from pymongo import MongoClient
from pymongo.collection import Collection

from .parser import ParsedPage, ImageInfo


# Default paths
DATA_DIR = Path("data/raw")
IMAGES_DIR = DATA_DIR / "images"
PDFS_DIR = DATA_DIR / "pdfs"


class Storage:
    """Handles all persistence: MongoDB for metadata, filesystem for binaries."""
    
    def __init__(
        self, 
        mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
        db_name: str = "erica",
        data_dir: str | Path = DATA_DIR
    ):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # Collections
        self.pages: Collection = self.db.pages
        self.resources: Collection = self.db.resources
        self.failures: Collection = self.db.failures
        
        # Filesystem paths
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.pdfs_dir = self.data_dir / "pdfs"
        
        # Ensure directories exist
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create indexes for efficient lookups
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create indexes for efficient querying."""
        self.pages.create_index("url", unique=True)
        self.resources.create_index("url", unique=True)
        self.resources.create_index("resource_type")
        self.resources.create_index("status")
        self.failures.create_index("url")
    
    def page_exists(self, url: str) -> bool:
        """Check if a page has already been ingested."""
        return self.pages.find_one({"url": url}) is not None
    
    def resource_exists(self, url: str) -> bool:
        """Check if a resource has already been recorded."""
        return self.resources.find_one({"url": url}) is not None
    
    def save_page(self, parsed: ParsedPage) -> None:
        """Save an ingested web page."""
        doc = {
            "url": parsed.url,
            "title": parsed.title,
            "content": parsed.content,
            "links_found": parsed.links,
            "ingested_at": datetime.now(timezone.utc)
        }
        
        self.pages.update_one(
            {"url": parsed.url},
            {"$set": doc},
            upsert=True
        )
    
    def save_resource(
        self,
        url: str,
        resource_type: str,
        discovered_from: str,
        status: str = "pending",
        local_path: str | None = None,
        metadata: dict | None = None
    ) -> None:
        """Save or update a discovered resource."""
        doc = {
            "url": url,
            "resource_type": resource_type,
            "discovered_from": discovered_from,
            "status": status,
            "local_path": local_path,
            "metadata": metadata or {},
            "ingested_at": datetime.now(timezone.utc) if status == "ingested" else None
        }
        
        self.resources.update_one(
            {"url": url},
            {"$set": doc},
            upsert=True
        )
    
    def save_image(
        self,
        image_info: ImageInfo,
        discovered_from: str,
        image_data: bytes,
        file_hash: str
    ) -> str:
        """
        Save an image to filesystem and record in MongoDB.
        Returns the local path.
        """
        # Determine extension
        ext = Path(image_info.original_filename).suffix.lower()
        if not ext:
            ext = '.png'  # Default
        
        # Save to filesystem
        filename = f"{file_hash}{ext}"
        local_path = self.images_dir / filename
        
        with open(local_path, 'wb') as f:
            f.write(image_data)
        
        # Record in MongoDB
        self.save_resource(
            url=image_info.url,
            resource_type="image",
            discovered_from=discovered_from,
            status="ingested",
            local_path=str(local_path),
            metadata={
                "alt_text": image_info.alt_text,
                "context": image_info.context,
                "original_filename": image_info.original_filename,
                "file_size": len(image_data)
            }
        )
        
        return str(local_path)
    
    def record_failure(
        self,
        url: str,
        failure_type: str,
        error_message: str,
        discovered_from: str | None = None,
        status_code: int | None = None
    ) -> None:
        """Record a failed fetch/parse attempt."""
        existing = self.failures.find_one({"url": url})
        
        now = datetime.now(timezone.utc)
        
        if existing:
            self.failures.update_one(
                {"url": url},
                {
                    "$set": {
                        "last_failed_at": now,
                        "error_message": error_message,
                        "status_code": status_code
                    },
                    "$inc": {"attempts": 1}
                }
            )
        else:
            self.failures.insert_one({
                "url": url,
                "failure_type": failure_type,
                "error_message": error_message,
                "discovered_from": discovered_from,
                "status_code": status_code,
                "attempts": 1,
                "first_failed_at": now,
                "last_failed_at": now
            })
    
    def get_stats(self) -> dict:
        """Get summary statistics of ingested content."""
        return {
            "pages": self.pages.count_documents({}),
            "resources": {
                "total": self.resources.count_documents({}),
                "by_type": {
                    "pdf": self.resources.count_documents({"resource_type": "pdf"}),
                    "video": self.resources.count_documents({"resource_type": "video"}),
                    "image": self.resources.count_documents({"resource_type": "image"}),
                    "external": self.resources.count_documents({"resource_type": "external"})
                },
                "by_status": {
                    "pending": self.resources.count_documents({"status": "pending"}),
                    "ingested": self.resources.count_documents({"status": "ingested"}),
                    "failed": self.resources.count_documents({"status": "failed"})
                }
            },
            "failures": self.failures.count_documents({})
        }
    
    def get_all_urls(self) -> dict:
        """Get all ingested URLs grouped by type."""
        return {
            "pages": [doc["url"] for doc in self.pages.find({}, {"url": 1})],
            "pdfs": [doc["url"] for doc in self.resources.find({"resource_type": "pdf"}, {"url": 1})],
            "videos": [doc["url"] for doc in self.resources.find({"resource_type": "video"}, {"url": 1})],
            "images": [doc["url"] for doc in self.resources.find({"resource_type": "image"}, {"url": 1})]
        }
    
    def clear_all(self) -> None:
        """Clear all collections. Use with caution!"""
        self.pages.delete_many({})
        self.resources.delete_many({})
        self.failures.delete_many({})
    
    def close(self):
        """Close MongoDB connection."""
        self.client.close()