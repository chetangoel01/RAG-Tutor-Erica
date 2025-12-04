"""
HTML parsing, content extraction, and link classification.
"""

import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from .utils import normalize_url, classify_url


@dataclass
class ImageInfo:
    """Information extracted about an image."""
    url: str
    alt_text: str = ""
    context: str = ""
    original_filename: str = ""


@dataclass
class ParsedPage:
    """Result of parsing an HTML page."""
    url: str
    title: str
    content: str
    links: dict = field(default_factory=lambda: {
        'internal': [],
        'pdf': [],
        'video': [],
        'image': [],
        'external': []
    })
    images: list[ImageInfo] = field(default_factory=list)


def parse_html(html: str, page_url: str) -> ParsedPage:
    """
    Parse an HTML page and extract content, links, and images.
    
    Args:
        html: Raw HTML string
        page_url: URL of the page (for resolving relative links)
    
    Returns:
        ParsedPage with extracted content and classified links
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extract title first (before any modifications)
    title = extract_title(soup)
    
    # IMPORTANT: Extract links from FULL HTML before stripping nav elements
    # This ensures we capture navigation links
    links = extract_links(soup, page_url)
    
    # Extract images with context (also before stripping)
    images = extract_images(soup, page_url)
    
    # Add image URLs to links dict
    links['image'] = [img.url for img in images]
    
    # NOW extract main content (this modifies soup by removing nav, etc.)
    # We create a fresh soup for content extraction to avoid side effects
    content_soup = BeautifulSoup(html, 'html.parser')
    content = extract_content(content_soup)
    
    return ParsedPage(
        url=page_url,
        title=title,
        content=content,
        links=links,
        images=images
    )


def extract_title(soup: BeautifulSoup) -> str:
    """Extract page title from HTML."""
    # Try <title> tag first
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    
    # Fall back to first <h1>
    h1 = soup.find('h1')
    if h1:
        return h1.get_text(strip=True)
    
    return "Untitled"


def extract_content(soup: BeautifulSoup) -> str:
    """
    Extract main text content from HTML, removing boilerplate.
    """
    # Remove script, style, nav, footer elements
    for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        element.decompose()
    
    # Try to find main content area
    main_content = (
        soup.find('main') or 
        soup.find('article') or 
        soup.find(class_=re.compile(r'content|main|post|article', re.I)) or
        soup.find('body')
    )
    
    if not main_content:
        main_content = soup
    
    # Get text with some structure preserved
    text = main_content.get_text(separator='\n', strip=True)
    
    # Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()


def extract_links(soup: BeautifulSoup, page_url: str) -> dict:
    """
    Extract all links from the page and classify them.
    
    Returns dict with keys: 'internal', 'pdf', 'video', 'external'
    """
    links = {
        'internal': [],
        'pdf': [],
        'video': [],
        'external': []
    }
    
    seen = set()
    
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        
        # Skip empty, javascript, and anchor-only links
        if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
            continue
        
        # Normalize URL
        url = normalize_url(href, page_url)
        
        # Skip duplicates
        if url in seen:
            continue
        seen.add(url)
        
        # Classify and store
        link_type = classify_url(url)
        if link_type in links:
            links[link_type].append(url)
        elif link_type == 'image':
            # Images from <a> tags go to external (likely downloads)
            links['external'].append(url)
        else:
            links['external'].append(url)
    
    return links


def extract_images(soup: BeautifulSoup, page_url: str) -> list[ImageInfo]:
    """
    Extract all images with their context (alt text, surrounding text).
    """
    images = []
    seen = set()
    
    for img in soup.find_all('img'):
        src = img.get('src', '')
        
        if not src or src.startswith('data:'):
            continue
        
        # Normalize URL
        url = normalize_url(src, page_url)
        
        # Skip duplicates
        if url in seen:
            continue
        seen.add(url)
        
        # Extract alt text
        alt_text = img.get('alt', '')
        
        # Extract context - try figure caption first, then surrounding paragraph
        context = extract_image_context(img)
        
        # Get original filename from URL
        original_filename = url.split('/')[-1].split('?')[0]
        
        images.append(ImageInfo(
            url=url,
            alt_text=alt_text,
            context=context,
            original_filename=original_filename
        ))
    
    return images


def extract_image_context(img_tag) -> str:
    """
    Extract contextual text around an image.
    Tries: figcaption, parent figure, surrounding paragraph.
    """
    # Check if inside a <figure> with <figcaption>
    figure = img_tag.find_parent('figure')
    if figure:
        caption = figure.find('figcaption')
        if caption:
            return caption.get_text(strip=True)
    
    # Try to get surrounding paragraph
    parent = img_tag.parent
    while parent and parent.name not in ['p', 'div', 'section', 'article', 'body']:
        parent = parent.parent
    
    if parent and parent.name in ['p', 'div']:
        text = parent.get_text(strip=True)
        # Limit context length
        if len(text) > 500:
            text = text[:500] + "..."
        return text
    
    return ""