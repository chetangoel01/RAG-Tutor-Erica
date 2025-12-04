"""
Web crawler for ingesting course content.
"""

import logging
import time
from collections import deque

import requests

from .parser import parse_html
from .storage import Storage
from .utils import (
    COURSE_ROOT,
    classify_url,
    is_internal_page,
    normalize_url,
    url_to_hash,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class Crawler:
    """
    BFS crawler for the course website.
    
    Extracts page content, discovers and classifies links,
    downloads images, and stores everything in MongoDB.
    """
    
    def __init__(
        self,
        storage: Storage,
        delay: float = 1.0,
        timeout: int = 30,
        max_retries: int = 1,
        progress_interval: int = 10
    ):
        self.storage = storage
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.progress_interval = progress_interval
        
        # Crawl state
        self.queue: deque[str] = deque()
        self.visited: set[str] = set()
        
        # Stats
        self.pages_processed = 0
        self.images_downloaded = 0
        self.resources_found = 0
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'EricaTutor/1.0 (Educational Project)'
        })
    
    def crawl(self, start_url: str = COURSE_ROOT) -> None:
        """
        Start crawling from the given URL.
        
        Args:
            start_url: URL to start crawling from (default: course root)
        """
        logger.info(f"Starting crawl from {start_url}")
        start_time = time.time()
        
        # Initialize queue
        self.queue.append(normalize_url(start_url))
        
        try:
            while self.queue:
                url = self.queue.popleft()
                
                # Skip if already visited
                if url in self.visited:
                    continue
                
                self.visited.add(url)
                
                # Process the page
                success = self._process_page(url)
                
                if success:
                    self.pages_processed += 1
                
                # Progress update
                if self.pages_processed % self.progress_interval == 0:
                    logger.info(
                        f"Progress: {self.pages_processed} pages done, "
                        f"{len(self.queue)} in queue, "
                        f"{self.resources_found} resources found"
                    )
                
                # Rate limiting
                if self.queue:
                    time.sleep(self.delay)
        
        except KeyboardInterrupt:
            logger.warning("Crawl interrupted by user")
        
        finally:
            # Final summary
            elapsed = time.time() - start_time
            self._print_summary(elapsed)
    
    def _process_page(self, url: str) -> bool:
        """
        Process a single page: fetch, parse, extract links, save.
        
        Returns True if successful, False otherwise.
        """
        # Fetch page
        html = self._fetch_page(url)
        if html is None:
            return False
        
        # Parse content
        try:
            parsed = parse_html(html, url)
        except Exception as e:
            logger.warning(f"Parse error for {url}: {e}")
            self.storage.record_failure(
                url=url,
                failure_type="parse_error",
                error_message=str(e)
            )
            return False
        
        # Save page
        self.storage.save_page(parsed)
        
        # Log page info
        link_counts = f"{len(parsed.links['internal'])} internal, {len(parsed.links['pdf'])} pdfs, {len(parsed.images)} images"
        logger.info(f"[{self.pages_processed + 1}] {url} - {link_counts}")
        
        # Queue internal links for crawling
        for link in parsed.links['internal']:
            if link not in self.visited and is_internal_page(link):
                self.queue.append(link)
        
        # Process discovered resources
        self._process_resources(parsed, url)
        
        # Download images
        self._download_images(parsed.images, url)
        
        return True
    
    def _fetch_page(self, url: str) -> str | None:
        """
        Fetch a page with retry logic.
        
        Returns HTML string or None if failed.
        """
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                
                if response.status_code == 200:
                    return response.text
                
                elif response.status_code == 404:
                    logger.warning(f"Not found (404): {url}")
                    self.storage.record_failure(
                        url=url,
                        failure_type="http_error",
                        error_message="Page not found",
                        status_code=404
                    )
                    return None
                
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}")
                    if attempt < self.max_retries:
                        time.sleep(self.delay * 2)
                        continue
                    
                    self.storage.record_failure(
                        url=url,
                        failure_type="http_error",
                        error_message=f"HTTP {response.status_code}",
                        status_code=response.status_code
                    )
                    return None
            
            except requests.Timeout:
                logger.warning(f"Timeout for {url}")
                if attempt < self.max_retries:
                    time.sleep(self.delay * 2)
                    continue
                
                self.storage.record_failure(
                    url=url,
                    failure_type="timeout",
                    error_message="Request timed out"
                )
                return None
            
            except requests.RequestException as e:
                logger.warning(f"Request error for {url}: {e}")
                self.storage.record_failure(
                    url=url,
                    failure_type="http_error",
                    error_message=str(e)
                )
                return None
        
        return None
    
    def _process_resources(self, parsed, page_url: str) -> None:
        """Record discovered PDFs, videos, and external links."""
        # PDFs
        for pdf_url in parsed.links['pdf']:
            if not self.storage.resource_exists(pdf_url):
                self.storage.save_resource(
                    url=pdf_url,
                    resource_type="pdf",
                    discovered_from=page_url,
                    status="pending"
                )
                self.resources_found += 1
        
        # Videos
        for video_url in parsed.links['video']:
            if not self.storage.resource_exists(video_url):
                self.storage.save_resource(
                    url=video_url,
                    resource_type="video",
                    discovered_from=page_url,
                    status="pending"
                )
                self.resources_found += 1
        
        # External links (just track them)
        for ext_url in parsed.links['external']:
            if not self.storage.resource_exists(ext_url):
                self.storage.save_resource(
                    url=ext_url,
                    resource_type="external",
                    discovered_from=page_url,
                    status="skipped"
                )
    
    def _download_images(self, images, page_url: str) -> None:
        """Download images and save to filesystem."""
        for img_info in images:
            # Skip if already downloaded
            if self.storage.resource_exists(img_info.url):
                continue
            
            try:
                response = self.session.get(img_info.url, timeout=self.timeout)
                
                if response.status_code == 200:
                    file_hash = url_to_hash(img_info.url)
                    self.storage.save_image(
                        image_info=img_info,
                        discovered_from=page_url,
                        image_data=response.content,
                        file_hash=file_hash
                    )
                    self.images_downloaded += 1
                else:
                    self.storage.record_failure(
                        url=img_info.url,
                        failure_type="download_error",
                        error_message=f"HTTP {response.status_code}",
                        discovered_from=page_url,
                        status_code=response.status_code
                    )
            
            except requests.RequestException as e:
                self.storage.record_failure(
                    url=img_info.url,
                    failure_type="download_error",
                    error_message=str(e),
                    discovered_from=page_url
                )
    
    def _print_summary(self, elapsed: float) -> None:
        """Print final crawl summary."""
        stats = self.storage.get_stats()
        
        logger.info("")
        logger.info("=" * 50)
        logger.info("CRAWL COMPLETE")
        logger.info("=" * 50)
        logger.info(f"Time elapsed: {elapsed:.1f}s")
        logger.info(f"Pages ingested: {stats['pages']}")
        logger.info(f"Images downloaded: {stats['resources']['by_type']['image']}")
        logger.info(f"PDFs discovered: {stats['resources']['by_type']['pdf']}")
        logger.info(f"Videos discovered: {stats['resources']['by_type']['video']}")
        logger.info(f"Failures logged: {stats['failures']}")
        
        if stats['failures'] > 0:
            logger.info(f"  (run db.failures.find() to review)")
        logger.info("=" * 50)


def run_crawler(
    mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
    start_url: str = COURSE_ROOT,
    delay: float = 1.0
) -> Storage:
    """
    Convenience function to run the crawler.
    
    Returns the Storage instance for further queries.
    """
    storage = Storage(mongo_uri=mongo_uri)
    crawler = Crawler(storage=storage, delay=delay)
    crawler.crawl(start_url)
    return storage