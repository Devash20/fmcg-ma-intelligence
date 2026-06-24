"""
Real-Time FMCG M&A Data Ingestion
==================================
Fetches live news from:
  - Google News API
  - SEC EDGAR filings (10-K, 8-K)
  - RSS feeds (FoodBev, Reuters, Bloomberg)
  - NewsAPI + Newsdata.io
  
Updates the pipeline with fresh data every run.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import requests
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict
import feedparser
import os


def load_env(env_path=".env"):
    """Load environment variables from a .env file if it exists."""
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        v_clean = v.strip().strip('"').strip("'")
                        os.environ[k.strip()] = v_clean
        except Exception as e:
            print(f"[Env] Warning: Failed to load .env: {e}")


class RealTimeIngestion:
    """Fetch live FMCG M&A deal news from multiple sources."""
    
    def __init__(self):
        load_env()
        self.fmcg_keywords = [
            "FMCG", "M&A", "acquisition", "merger", "deal",
            "PepsiCo", "Coca-Cola", "Nestlé", "Unilever", "Danone",
            "Mars", "Ferrero", "Kimberly-Clark", "Hershey", "McCormick",
            "food", "beverage", "snacking", "dairy", "personal care"
        ]
        self.raw_articles = []

    def fetch_newsapi(self, api_key: str = None) -> List[Dict]:
        """Fetch from NewsAPI.org (requires free API key from newsapi.org)."""
        if not api_key:
            api_key = os.getenv("NEWSAPI_KEY", "")
        
        articles = []
        if not api_key or api_key == "demo" or api_key == "your_newsapi_key_here":
            print("[NewsAPI] No valid API key set. Skipping NewsAPI live fetch.")
            return articles
            
        query = "FMCG acquisition merger investment deal 2025 2026"
        url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&language=en&pageSize=100"
        
        try:
            print(f"[NewsAPI] Fetching live FMCG M&A news...")
            response = requests.get(url, headers={"Authorization": api_key}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for article in data.get("articles", [])[:20]:
                    articles.append({
                        "headline": article.get("title") or "",
                        "url": article.get("url") or "",
                        "source": article.get("source", {}).get("name") or "NewsAPI",
                        "published": article.get("publishedAt") or datetime.now().isoformat(),
                        "summary": article.get("description") or article.get("content") or "",
                        "fetch_method": "NewsAPI"
                    })
                print(f"[NewsAPI] Fetched {len(articles)} articles.")
            else:
                print(f"[NewsAPI] Failed (HTTP Status: {response.status_code})")
        except Exception as e:
            print(f"[NewsAPI] Error: {e}")
        return articles

    def fetch_rss_feeds(self) -> List[Dict]:
        """Fetch from industry RSS feeds (FoodBev, Reuters, Bloomberg)."""
        articles = []
        feeds = {
            "FoodBev": "https://www.foodbev.com/feed/",
            "Reuters Food": "https://feeds.reuters.com/food-agriculture",
            "FMCG News": "https://www.fmcgnewsdesk.com/feed/",
        }
        
        for source, feed_url in feeds.items():
            try:
                print(f"[RSS] Fetching {source}...")
                feed = feedparser.parse(feed_url)
                count = 0
                for entry in feed.entries[:15]:
                    title = entry.get('title', '')
                    summary = entry.get('summary', '') or entry.get('description', '') or ''
                    text_to_check = f"{title} {summary}"
                    if any(kw.lower() in text_to_check.lower() for kw in self.fmcg_keywords):
                        articles.append({
                            "headline": title,
                            "url": entry.get('link', ''),
                            "source": source,
                            "published": entry.get('published', datetime.now().isoformat()),
                            "summary": summary,
                            "fetch_method": "RSS Feed"
                        })
                        count += 1
                print(f"[RSS] {source} — fetched {count} relevant articles")
            except Exception as e:
                print(f"[RSS] {source} error: {e}")
        
        return articles

    def fetch_sec_edgar(self) -> List[Dict]:
        """Fetch from SEC EDGAR — Forms 8-K (current events), 425 (merger prospectus)."""
        articles = []
        
        # SEC EDGAR API endpoint for recent filings
        sec_api_url = "https://data.sec.gov/submissions/CIK{cik}.json"
        
        # Major FMCG companies' CIK numbers
        companies = {
            "PepsiCo": "0000077476",
            "Coca-Cola": "0000021344",
            "Nestlé": "0001099659",  # US-listed ADR
            "Unilever": "0000217410",
            "Danone": "0001527346",
            "Kimberly-Clark": "0000055785",
            "McCormick": "0000063754",
        }
        
        # SEC guidelines request a custom User-Agent header
        headers = {
            "User-Agent": "FMCG Intel Agent research@fmcg-intel.com"
        }
        
        for company, cik in companies.items():
            try:
                print(f"[SEC EDGAR] Querying {company}...")
                url = sec_api_url.format(cik=cik)
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    recent = data.get("filings", {}).get("recent", {})
                    if not recent:
                        continue
                    
                    forms = recent.get("form", [])
                    filing_dates = recent.get("filingDate", [])
                    accession_nums = recent.get("accessionNumber", [])
                    primary_docs = recent.get("primaryDocument", [])
                    items_list = recent.get("items", [])
                    
                    count = 0
                    for i in range(min(15, len(forms))):
                        form = forms[i]
                        if form in ["8-K", "425"]:
                            # Filter for M&A items: 1.01 (Entry into a Material Definitive Agreement)
                            # or 2.01 (Completion of Acquisition or Disposition of Assets)
                            items = items_list[i] if i < len(items_list) else ""
                            is_mna_related = (form == "425") or ("1.01" in str(items) or "2.01" in str(items))
                            
                            if is_mna_related:
                                accession_num = accession_nums[i]
                                accession_no_hyphen = accession_num.replace("-", "")
                                primary_doc = primary_docs[i]
                                cik_int = str(int(cik))
                                doc_link = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_hyphen}/{primary_doc}"
                                
                                articles.append({
                                    "headline": f"{company} SEC Filing: Form {form} (Filing Date: {filing_dates[i]})",
                                    "url": doc_link,
                                    "source": "SEC EDGAR",
                                    "published": filing_dates[i],
                                    "summary": f"Form {form} filing under SEC EDGAR for {company}. Items reported: {items}.",
                                    "fetch_method": "SEC EDGAR API"
                                })
                                count += 1
                    print(f"[SEC EDGAR] {company} — found {count} relevant filings")
                else:
                    print(f"[SEC EDGAR] {company} query failed (HTTP {response.status_code})")
            except Exception as e:
                print(f"[SEC EDGAR] {company} error: {e}")
        
        return articles

    def fetch_google_news(self) -> List[Dict]:
        """Fetch from Google News (no API key needed, uses RSS)."""
        articles = []
        google_news_url = "https://news.google.com/rss/search?q=FMCG+acquisition+merger+deal&hl=en-US&gl=US&ceid=US:en"
        
        try:
            print(f"[Google News] Fetching FMCG M&A headlines...")
            feed = feedparser.parse(google_news_url)
            for entry in feed.entries[:20]:
                articles.append({
                    "headline": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": "Google News",
                    "published": entry.get("published", datetime.now().isoformat()),
                    "summary": entry.get("summary", ""),
                    "fetch_method": "Google News RSS"
                })
            print(f"[Google News] Fetched {len(articles)} headlines")
            return articles
        except Exception as e:
            print(f"[Google News] Error: {e}")
            return articles

    def fetch_press_releases(self) -> List[Dict]:
        """Fetch from company press release sites / BusinessWire."""
        articles = []
        feed_url = "https://feed.businesswire.com/rss/home/?rss=G1N7BF1KX0tTXlRZXQ=="
        
        try:
            print(f"[Press Releases] Fetching BusinessWire M&A news...")
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                articles.append({
                    "headline": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": "BusinessWire",
                    "published": entry.get("published", datetime.now().isoformat()),
                    "summary": entry.get("summary", ""),
                    "fetch_method": "BusinessWire RSS"
                })
            print(f"[Press Releases] Fetched {len(articles)} press releases")
            return articles
        except Exception as e:
            print(f"[Press Releases] Error: {e}")
            return articles

    def ingest_all(self) -> List[Dict]:
        """Run all ingestion sources in parallel and aggregate."""
        print("\n" + "="*60)
        print("  REAL-TIME FMCG M&A DATA INGESTION")
        print("="*60 + "\n")
        
        all_articles = []
        
        # Fetch from all sources
        print("Stage 1: Fetching from multiple live sources...\n")
        all_articles.extend(self.fetch_newsapi())
        all_articles.extend(self.fetch_rss_feeds())
        all_articles.extend(self.fetch_sec_edgar())
        all_articles.extend(self.fetch_google_news())
        all_articles.extend(self.fetch_press_releases())
        
        print(f"\n[Ingestion Complete] {len(all_articles)} raw articles fetched")
        print(f"[Timestamp] {datetime.now().isoformat()}")
        
        self.raw_articles = all_articles
        return all_articles


class StructuredExtractor:
    """Extract structured deal data from raw articles using regex + heuristics."""
    
    def extract_from_text(self, articles: List[Dict]) -> List[Dict]:
        """
        Parse raw article text to extract:
        - Acquirer name
        - Target company name
        - Deal value (if mentioned)
        - Deal type (acquisition, merger, investment, etc.)
        - Category (food, beverage, personal care, etc.)
        - Status (announced, completed, pending, failed, etc.)
        """
        deals = []
        
        # Regex patterns for deal extraction
        patterns = {
            "deal_value": r"\$?([\d,\.]+)\s*(?:billion|million|B|M|bn)",
            "acquirer_target": r"(\w+(?:\s+\w+)?)\s+(?:acquires?|buys?|merges?\s+with)\s+(\w+(?:\s+\w+)?)",
            "deal_type": r"(acquisition|merger|investment|stake|divestiture|spinoff)",
            "status": r"(announced|completed|approved|pending|failed|shelved|abandoned|collapsed)",
            "category": r"(food|beverage|snacking|personal care|dairy|coffee|spirits|health|wellness|ingredients)"
        }
        
        for i, article in enumerate(articles):
            headline = article.get("headline", "")
            summary = article.get("summary", "")
            text = f"{headline} {summary}".lower()
            
            deal = {
                "id": f"live_{i}_{datetime.now().timestamp()}",
                "headline": headline,
                "source": article.get("source", "Unknown"),
                "source_url": article.get("url", ""),
                "published": article.get("published", datetime.now().isoformat()),
                "fetch_method": article.get("fetch_method", "Unknown"),
                "raw_text": text[:200],
            }
            
            # Extract using regex
            val_match = re.search(patterns["deal_value"], text, re.IGNORECASE)
            deal_val = None
            if val_match:
                try:
                    val_str = val_match.group(1).replace(",", "")
                    if val_str and val_str != ".":
                        deal_val = float(val_str)
                except ValueError:
                    pass
            deal["deal_value_usd"] = deal_val
            
            acq_match = re.search(patterns["acquirer_target"], text, re.IGNORECASE)
            if acq_match:
                deal["acquirer"] = acq_match.group(1).title()
                deal["target"] = acq_match.group(2).title()
            
            type_match = re.search(patterns["deal_type"], text, re.IGNORECASE)
            deal["deal_type"] = type_match.group(1).title() if type_match else "M&A Activity"
            
            status_match = re.search(patterns["status"], text, re.IGNORECASE)
            deal["status"] = status_match.group(1).title() if status_match else "Reported"
            
            cat_match = re.search(patterns["category"], text, re.IGNORECASE)
            deal["category"] = cat_match.group(1).title() if cat_match else "FMCG"
            
            deal["credibility_tier"] = self._assess_credibility(article.get("source", ""))
            
            deals.append(deal)
        
        return deals
    
    def _assess_credibility(self, source: str) -> str:
        """Assign credibility tier based on source."""
        tier1 = ["sec.gov", "sec filing", "press release", "official"]
        tier2 = ["foodbev", "mbs group", "reuters", "bloomberg", "businesswire", "newsapi"]
        
        source_lower = source.lower()
        if any(t in source_lower for t in tier1):
            return "Tier 1 - Official"
        elif any(t in source_lower for t in tier2):
            return "Tier 2 - Trade/News"
        else:
            return "Tier 3 - General"


def run_live_ingest():
    """Main entry point for real-time ingestion."""
    
    # Stage 1: Fetch raw articles
    ingester = RealTimeIngestion()
    raw_articles = ingester.ingest_all()
    
    # Stage 2: Extract structured data
    extractor = StructuredExtractor()
    structured_deals = extractor.extract_from_text(raw_articles)
    
    print(f"\n[Extracted] {len(structured_deals)} structured deals from raw articles")
    
    # Save raw ingestion output
    output = {
        "timestamp": datetime.now().isoformat(),
        "raw_article_count": len(raw_articles),
        "raw_articles": raw_articles,
        "structured_deals": structured_deals,
        "sources_queried": [
            "NewsAPI",
            "RSS feeds (FoodBev, Reuters, FMCG Newsdesk)",
            "SEC EDGAR filings (8-K, 425)",
            "Google News",
            "Press Release sites"
        ]
    }
    
    # Save to file
    with open("live_ingestion_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n[Output] Live ingestion data saved to live_ingestion_output.json")
    
    return structured_deals


if __name__ == "__main__":
    live_deals = run_live_ingest()
    print("\nSample extracted deal (if available):")
    if live_deals:
        print(json.dumps(live_deals[0], indent=2, default=str))
    else:
        print("(No live data fetched — requires API keys for NewsAPI, SEC EDGAR access)")
