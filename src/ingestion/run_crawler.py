#!/usr/bin/env python3
"""
Run the course website crawler.

Usage:
    python -m src.ingestion.run_crawler
    
    # Or with options:
    python -m src.ingestion.run_crawler --delay 2.0 --clear
"""

import argparse
import sys
from pathlib import Path

# Add src to path if running directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingestion import run_crawler, Storage, COURSE_ROOT


def main():
    parser = argparse.ArgumentParser(description='Crawl the AI course website')
    parser.add_argument(
        '--start-url',
        default=COURSE_ROOT,
        help='URL to start crawling from'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds'
    )
    parser.add_argument(
        '--mongo-uri',
        default='mongodb://erica:erica_password_123@localhost:27017/',
        help='MongoDB connection URI'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear existing data before crawling'
    )
    
    args = parser.parse_args()
    
    # Clear if requested
    if args.clear:
        print("Clearing existing data...")
        storage = Storage(mongo_uri=args.mongo_uri)
        storage.clear_all()
        storage.close()
        print("Data cleared.")
    
    # Run crawler
    storage = run_crawler(
        mongo_uri=args.mongo_uri,
        start_url=args.start_url,
        delay=args.delay
    )
    
    # Print all URLs for M2 requirement
    print("\n" + "=" * 50)
    print("ALL INGESTED URLs")
    print("=" * 50)
    
    urls = storage.get_all_urls()
    
    print(f"\n📄 Pages ({len(urls['pages'])}):")
    for url in sorted(urls['pages']):
        print(f"  {url}")
    
    print(f"\n📕 PDFs ({len(urls['pdfs'])}):")
    for url in sorted(urls['pdfs']):
        print(f"  {url}")
    
    print(f"\n🎥 Videos ({len(urls['videos'])}):")
    for url in sorted(urls['videos']):
        print(f"  {url}")
    
    print(f"\n🖼️  Images ({len(urls['images'])}):")
    print(f"  ({len(urls['images'])} images - run storage.get_all_urls()['images'] for full list)")
    
    storage.close()


if __name__ == '__main__':
    main()