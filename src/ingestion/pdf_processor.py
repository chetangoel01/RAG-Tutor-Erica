"""
PDF download and text extraction.
"""

import logging
from pathlib import Path

import requests
from pypdf import PdfReader

from .storage import Storage
from .utils import url_to_hash

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Download PDFs and extract text content."""
    
    def __init__(
        self,
        storage: Storage,
        timeout: int = 60,
        max_pages: int = None  # None = all pages
    ):
        self.storage = storage
        self.timeout = timeout
        self.max_pages = max_pages
        
        # Ensure directory exists
        self.storage.pdfs_dir.mkdir(parents=True, exist_ok=True)
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'EricaTutor/1.0 (Educational Project)'
        })
        
        # Stats
        self.processed = 0
        self.failed = 0
    
    def process_all_pending(self) -> None:
        """Process all PDFs with status 'pending'."""
        pending = list(self.storage.resources.find({
            "resource_type": "pdf",
            "status": "pending"
        }))
        
        total = len(pending)
        logger.info(f"Processing {total} PDFs...")
        
        for i, doc in enumerate(pending, 1):
            url = doc['url']
            logger.info(f"[{i}/{total}] {url}")
            
            success = self.process_pdf(url, doc.get('discovered_from'))
            
            if success:
                self.processed += 1
            else:
                self.failed += 1
        
        logger.info(f"PDF processing complete. Success: {self.processed}, Failed: {self.failed}")
    
    def process_pdf(self, url: str, discovered_from: str = None) -> bool:
        """
        Download and extract text from a single PDF.
        
        Returns True if successful, False otherwise.
        """
        # Download PDF
        pdf_data = self._download_pdf(url)
        if pdf_data is None:
            return False
        
        # Save to filesystem
        file_hash = url_to_hash(url)
        filename = f"{file_hash}.pdf"
        local_path = self.storage.pdfs_dir / filename
        
        with open(local_path, 'wb') as f:
            f.write(pdf_data)
        
        # Extract text
        text, metadata = self._extract_text(local_path)
        
        if text is None:
            # PDF exists but couldn't extract text (might be scanned)
            self.storage.save_resource(
                url=url,
                resource_type="pdf",
                discovered_from=discovered_from,
                status="ingested",
                local_path=str(local_path),
                metadata={
                    "extraction_failed": True,
                    "error": metadata.get("error", "Unknown extraction error"),
                    "file_size": len(pdf_data)
                }
            )
            logger.warning(f"  Could not extract text (possibly scanned)")
            return True  # Still counts as processed
        
        # Update resource with extracted content
        self.storage.save_resource(
            url=url,
            resource_type="pdf",
            discovered_from=discovered_from,
            status="ingested",
            local_path=str(local_path),
            metadata={
                "page_count": metadata.get("page_count", 0),
                "file_size": len(pdf_data),
                "title": metadata.get("title"),
                "author": metadata.get("author"),
                "text_length": len(text)
            }
        )
        
        # Store extracted text in a separate field for easy querying
        self.storage.resources.update_one(
            {"url": url},
            {"$set": {"content": text}}
        )
        
        logger.info(f"  Extracted {len(text)} chars from {metadata.get('page_count', '?')} pages")
        return True
    
    def _download_pdf(self, url: str) -> bytes | None:
        """Download PDF from URL."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                return response.content
            
            logger.warning(f"  HTTP {response.status_code}")
            self.storage.record_failure(
                url=url,
                failure_type="download_error",
                error_message=f"HTTP {response.status_code}",
                status_code=response.status_code
            )
            
            # Mark as failed
            self.storage.resources.update_one(
                {"url": url},
                {"$set": {"status": "failed"}}
            )
            return None
            
        except requests.RequestException as e:
            logger.warning(f"  Download failed: {e}")
            self.storage.record_failure(
                url=url,
                failure_type="download_error",
                error_message=str(e)
            )
            self.storage.resources.update_one(
                {"url": url},
                {"$set": {"status": "failed"}}
            )
            return None
    
    def _extract_text(self, pdf_path: Path) -> tuple[str | None, dict]:
        """
        Extract text from a PDF file.
        
        Returns (text, metadata) tuple. text is None if extraction failed.
        """
        metadata = {}
        
        try:
            reader = PdfReader(pdf_path)
            
            metadata["page_count"] = len(reader.pages)
            
            # Get document metadata if available
            if reader.metadata:
                metadata["title"] = reader.metadata.get("/Title")
                metadata["author"] = reader.metadata.get("/Author")
            
            # Extract text from pages
            pages_to_process = reader.pages
            if self.max_pages:
                pages_to_process = pages_to_process[:self.max_pages]
            
            text_parts = []
            for page in pages_to_process:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            if not text_parts:
                metadata["error"] = "No extractable text found"
                return None, metadata
            
            text = "\n\n".join(text_parts)
            return text, metadata
            
        except Exception as e:
            metadata["error"] = str(e)
            logger.warning(f"  Extraction error: {e}")
            return None, metadata


def process_pdfs(
    mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
    db_name: str = "erica"
) -> None:
    """Convenience function to process all pending PDFs."""
    storage = Storage(mongo_uri=mongo_uri, db_name=db_name)
    processor = PDFProcessor(storage=storage)
    processor.process_all_pending()
    storage.close()