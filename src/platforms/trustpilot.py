"""Trustpilot review monitor — scrapes new reviews from SplitStay's Trustpilot page."""

from __future__ import annotations

import logging
from datetime import datetime

from src.models import TrustpilotReview

logger = logging.getLogger(__name__)


class TrustpilotMonitor:
    """Monitors SplitStay's Trustpilot page for new reviews."""
    
    def __init__(self, url: str = "https://www.trustpilot.com/review/splitstay.travel"):
        self.url = url
        self._browser = None
    
    async def check_for_reviews(self) -> list[TrustpilotReview]:
        """Scrape the Trustpilot page and return all visible reviews."""
        reviews = []
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto(self.url, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)  # Wait for dynamic content
                
                # Extract review cards
                review_cards = await page.query_selector_all(
                    'article[data-service-review-card-paper="true"], '
                    '.styles_reviewCard__hcAvl, '
                    '[data-review-id]'
                )
                
                for card in review_cards:
                    try:
                        review = await self._parse_review_card(card)
                        if review:
                            reviews.append(review)
                    except Exception as e:
                        logger.debug(f"Failed to parse review card: {e}")
                
                # Fallback: try parsing from page text if no cards found
                if not reviews:
                    body_text = await page.inner_text("body")
                    reviews = self._parse_from_text(body_text)
                
                await browser.close()
        
        except ImportError:
            logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        except Exception as e:
            logger.error(f"Failed to scrape Trustpilot: {e}")
        
        return reviews
    
    async def _parse_review_card(self, card) -> TrustpilotReview | None:
        """Parse a single review card element."""
        try:
            # Get reviewer name
            name_el = await card.query_selector(
                '[data-consumer-name-typography="true"], .styles_consumerName__dP8Um'
            )
            reviewer = await name_el.inner_text() if name_el else "Anonymous"
            
            # Get star rating
            rating_el = await card.query_selector(
                '[data-rating], .star-rating_starRating__4rrcf img'
            )
            rating = 5  # Default
            if rating_el:
                rating_attr = await rating_el.get_attribute("data-rating")
                if rating_attr:
                    rating = int(rating_attr)
            
            # Get title
            title_el = await card.query_selector(
                '[data-service-review-title-typography="true"], h2'
            )
            title = await title_el.inner_text() if title_el else ""
            
            # Get content
            content_el = await card.query_selector(
                '[data-service-review-text-typography="true"], p'
            )
            content = await content_el.inner_text() if content_el else ""
            
            # Get date
            date_el = await card.query_selector("time")
            date_str = ""
            if date_el:
                date_str = await date_el.get_attribute("datetime") or await date_el.inner_text()
            
            if not reviewer and not title and not content:
                return None
            
            return TrustpilotReview(
                reviewer=reviewer.strip(),
                rating=rating,
                title=title.strip(),
                content=content.strip(),
                date=date_str.strip(),
            )
        
        except Exception as e:
            logger.debug(f"Review card parse error: {e}")
            return None
    
    def _parse_from_text(self, body_text: str) -> list[TrustpilotReview]:
        """Fallback: try to parse reviews from raw page text."""
        # This is a last-resort parser — it's fragile but better than nothing
        reviews = []
        logger.info("Using text fallback parser for Trustpilot")
        
        # Look for patterns like "Rated 5 out of 5" or star indicators
        lines = body_text.split("\n")
        current_review: dict = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if "Rated" in line and "out of 5" in line:
                # Save previous review if exists
                if current_review.get("title"):
                    try:
                        reviews.append(TrustpilotReview(**current_review))
                    except Exception:
                        pass
                
                # Start new review
                try:
                    rating = int(line.split("Rated")[1].split("out")[0].strip())
                except (ValueError, IndexError):
                    rating = 5
                
                current_review = {
                    "reviewer": "Anonymous",
                    "rating": rating,
                    "title": "",
                    "content": "",
                    "date": "",
                }
        
        # Don't forget the last review
        if current_review.get("title"):
            try:
                reviews.append(TrustpilotReview(**current_review))
            except Exception:
                pass
        
        return reviews
