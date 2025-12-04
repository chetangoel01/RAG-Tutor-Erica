"""
YouTube video transcript extraction.
"""

import logging
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    CouldNotRetrieveTranscript
)

from .storage import Storage
from .utils import extract_youtube_video_id

logger = logging.getLogger(__name__)


class YouTubeProcessor:
    """Fetch transcripts from YouTube videos."""
    
    def __init__(self, storage: Storage):
        self.storage = storage
        
        # Stats
        self.processed = 0
        self.failed = 0
    
    def process_all_pending(self) -> None:
        """Process all YouTube videos with status 'pending'."""
        pending = list(self.storage.resources.find({
            "resource_type": "video",
            "status": "pending"
        }))
        
        total = len(pending)
        logger.info(f"Processing {total} YouTube videos...")
        
        for i, doc in enumerate(pending, 1):
            url = doc['url']
            logger.info(f"[{i}/{total}] {url}")
            
            success = self.process_video(url, doc.get('discovered_from'))
            
            if success:
                self.processed += 1
            else:
                self.failed += 1
        
        logger.info(f"YouTube processing complete. Success: {self.processed}, Failed: {self.failed}")
    
    def process_video(self, url: str, discovered_from: str = None) -> bool:
        """
        Fetch transcript for a single YouTube video.
        
        Returns True if successful, False otherwise.
        """
        # Extract video ID
        video_id = extract_youtube_video_id(url)
        
        if not video_id:
            logger.warning(f"  Could not extract video ID from URL")
            self.storage.record_failure(
                url=url,
                failure_type="parse_error",
                error_message="Could not extract video ID",
                discovered_from=discovered_from
            )
            self.storage.resources.update_one(
                {"url": url},
                {"$set": {"status": "failed"}}
            )
            return False
        
        # Fetch transcript
        transcript_data = self._fetch_transcript(video_id, url)
        
        if transcript_data is None:
            self.storage.resources.update_one(
                {"url": url},
                {"$set": {"status": "failed"}}
            )
            return False
        
        transcript_text, metadata = transcript_data
        
        # Update resource
        self.storage.save_resource(
            url=url,
            resource_type="video",
            discovered_from=discovered_from,
            status="ingested",
            local_path=None,
            metadata={
                "video_id": video_id,
                "language": metadata.get("language"),
                "is_auto_generated": metadata.get("is_auto_generated", False),
                "duration_seconds": metadata.get("duration"),
                "text_length": len(transcript_text)
            }
        )
        
        # Store transcript text
        self.storage.resources.update_one(
            {"url": url},
            {"$set": {"content": transcript_text}}
        )
        
        logger.info(f"  Extracted {len(transcript_text)} chars ({metadata.get('language', 'unknown')} language)")
        return True
    
    def _fetch_transcript(self, video_id: str, url: str) -> tuple[str, dict] | None:
        """
        Fetch transcript from YouTube using youtube-transcript-api.
        
        Returns (transcript_text, metadata) or None if failed.
        """
        try:
            # Create instance and get list of available transcripts
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            
            # Find best transcript - prefer manual English, then auto-generated
            transcript_info = None
            is_auto = False
            language = None
            
            # Convert to list to allow multiple iterations
            available_transcripts = list(transcript_list)
            
            # First pass: look for manual English transcript
            for transcript in available_transcripts:
                if transcript.language_code.startswith('en') and not transcript.is_generated:
                    transcript_info = transcript
                    language = transcript.language_code
                    is_auto = False
                    break
            
            # Second pass: look for auto-generated English
            if transcript_info is None:
                for transcript in available_transcripts:
                    if transcript.language_code.startswith('en') and transcript.is_generated:
                        transcript_info = transcript
                        language = transcript.language_code
                        is_auto = True
                        break
            
            # Third pass: try using find methods, then take any available transcript
            if transcript_info is None:
                try:
                    transcript_info = transcript_list.find_manually_created_transcript(['en'])
                    language = transcript_info.language_code
                    is_auto = False
                except:
                    try:
                        transcript_info = transcript_list.find_generated_transcript(['en'])
                        language = transcript_info.language_code
                        is_auto = True
                    except:
                        # Take first available transcript
                        if available_transcripts:
                            transcript_info = available_transcripts[0]
                            language = transcript_info.language_code
                            is_auto = transcript_info.is_generated
            
            if transcript_info is None:
                logger.warning(f"  No transcript available")
                self.storage.record_failure(
                    url=url,
                    failure_type="no_transcript",
                    error_message="No transcript available"
                )
                return None
            
            # Fetch the transcript content
            transcript_data = transcript_info.fetch()
            
            # Combine snippets into full text
            # transcript_data is a list of FetchedTranscriptSnippet objects with .text, .start, .duration attributes
            text_parts = [entry.text for entry in transcript_data]
            full_text = ' '.join(text_parts)
            
            # Calculate duration from last entry
            duration = None
            if transcript_data:
                last_entry = transcript_data[-1]
                duration = int(last_entry.start + last_entry.duration)
            
            metadata = {
                "language": language,
                "is_auto_generated": is_auto,
                "duration": duration,
                "segment_count": len(transcript_data)
            }
            
            return full_text, metadata
            
        except TranscriptsDisabled:
            logger.warning(f"  Transcripts disabled for this video")
            self.storage.record_failure(
                url=url,
                failure_type="transcripts_disabled",
                error_message="Transcripts are disabled for this video"
            )
            return None
        except NoTranscriptFound:
            logger.warning(f"  No transcript found for this video")
            self.storage.record_failure(
                url=url,
                failure_type="no_transcript",
                error_message="No transcript found for this video"
            )
            return None
        except VideoUnavailable:
            logger.warning(f"  Video unavailable")
            self.storage.record_failure(
                url=url,
                failure_type="video_unavailable",
                error_message="Video is unavailable"
            )
            return None
        except CouldNotRetrieveTranscript as e:
            error_msg = str(e)
            # Check error message for specific cases
            if "too many requests" in error_msg.lower() or "rate limit" in error_msg.lower():
                logger.warning(f"  Too many requests to YouTube")
                failure_type = "rate_limit"
            elif "request failed" in error_msg.lower():
                logger.warning(f"  YouTube request failed: {error_msg}")
                failure_type = "request_failed"
            else:
                logger.warning(f"  Could not retrieve transcript: {error_msg}")
                failure_type = "transcript_error"
            
            self.storage.record_failure(
                url=url,
                failure_type=failure_type,
                error_message=error_msg
            )
            return None
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"  Unexpected error: {error_msg}")
            self.storage.record_failure(
                url=url,
                failure_type="transcript_error",
                error_message=error_msg
            )
            return None


def process_youtube(
    mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
    db_name: str = "erica"
) -> None:
    """Convenience function to process all pending YouTube videos."""
    storage = Storage(mongo_uri=mongo_uri, db_name=db_name)
    processor = YouTubeProcessor(storage=storage)
    processor.process_all_pending()
    storage.close()