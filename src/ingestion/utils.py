"""
Utility functions for URL normalization, hashing, and domain checking.
"""

import hashlib
import re
from urllib.parse import urlparse, urljoin, urldefrag


# Base URL for the course - stay within this scope
ALLOWED_DOMAIN = "pantelis.github.io"
COURSE_ROOT = "https://pantelis.github.io/courses/ai/"

# Paths on pantelis.github.io that contain course-related content
# The site uses relative links that go to these directories
ALLOWED_PATHS = [
    '/courses/ai',
    '/aiml-common',
    '/book',
]

# Paths to explicitly exclude (other courses, unrelated content)
EXCLUDED_PATHS = [
    '/courses/robotics',
    '/courses/cv',
    '/data-mining',
]


def normalize_url(url: str, base_url: str = None) -> str:
    """
    Normalize a URL by:
    - Making it absolute (if base_url provided)
    - Removing fragments (#section)
    - Removing trailing slashes for consistency
    """
    if base_url:
        url = urljoin(base_url, url)
    
    # Remove fragment
    url, _ = urldefrag(url)
    
    # Remove trailing slash (except for root)
    if url.endswith('/') and not url.endswith('://'):
        url = url.rstrip('/')
    
    return url


def is_within_scope(url: str) -> bool:
    """Check if URL is within the allowed course website scope."""
    parsed = urlparse(url)
    
    # Must be on the allowed domain
    if parsed.netloc != ALLOWED_DOMAIN:
        return False
    
    path = parsed.path
    
    # Check if path is in excluded paths
    for excluded in EXCLUDED_PATHS:
        if path.startswith(excluded):
            return False
    
    # Check if path is in allowed paths
    for allowed in ALLOWED_PATHS:
        if path.startswith(allowed):
            return True
    
    # Also allow root-level pages that might be linked (like about.html)
    # but not crawl deeply into them
    return False


def is_internal_page(url: str) -> bool:
    """Check if URL is an internal HTML page (not a file download)."""
    if not is_within_scope(url):
        return False
    
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    # Exclude known non-page file extensions
    file_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', 
                       '.mp4', '.mp3', '.zip', '.pptx', '.ppt', '.docx', '.doc',
                       '.css', '.js', '.json', '.xml', '.rss']
    
    # .html is a page, not a download
    if path.endswith('.html'):
        return True
    
    return not any(path.endswith(ext) for ext in file_extensions)


def classify_url(url: str) -> str:
    """
    Classify a URL into resource types.
    Returns: 'internal', 'pdf', 'image', 'video', 'external', 'unknown'
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    # YouTube detection
    if 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc:
        return 'video'
    
    # File type detection by extension
    if path.endswith('.pdf'):
        return 'pdf'
    
    if any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']):
        return 'image'
    
    # Internal page
    if is_within_scope(url):
        return 'internal'
    
    # External link
    return 'external'


def url_to_hash(url: str) -> str:
    """Generate a short hash from URL for filenames."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def get_file_extension(url: str) -> str:
    """Extract file extension from URL."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf']:
        if path.endswith(ext):
            return ext
    
    return ''


def extract_youtube_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    parsed = urlparse(url)
    
    # youtu.be/VIDEO_ID
    if parsed.netloc == 'youtu.be':
        return parsed.path.strip('/')
    
    # youtube.com/watch?v=VIDEO_ID
    if 'youtube.com' in parsed.netloc:
        if 'v=' in url:
            match = re.search(r'v=([a-zA-Z0-9_-]+)', url)
            if match:
                return match.group(1)
        # youtube.com/embed/VIDEO_ID
        if '/embed/' in parsed.path:
            parts = parsed.path.split('/embed/')
            if len(parts) > 1:
                return parts[1].split('/')[0].split('?')[0]
    
    return None