# SplitStay Social Listener 🔍

Automated social listening tool that monitors accommodation-sharing signals across 8 countries, 10+ platforms, and 143+ events. Built for SplitStay's growth team to find people looking to share stays at festivals, conferences, and major events.

## What It Does

- **Scans 8 countries**: 🇪🇸 Spain, 🇬🇧 UK, 🇺🇸 US, 🇧🇷 Brazil, 🇩🇪 Germany, 🇹🇼 Taiwan, 🇨🇳 China, 🇵🇹 Portugal
- **Monitors 10+ platforms**: Reddit, X/Twitter, Facebook, Instagram, Discord, TikTok, Telegram, + regional platforms
- **Tracks signal types**: 🏠 Offering, 🔍 Seeking, 💸 Cost Pain, 👥 Group Forming, 🏷️ Brand Mentions, 🔍 Competitors
- **Posts to Slack** `#social-listening-tool` with direct links to source posts
- **Monitors Trustpilot** daily for new reviews
- **Tracks brand mentions** and competitor activity
- **Alerts on price spikes** for accommodation near events

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   SCHEDULER                      │
│  Monthly (15th): Country + Brand + Price scans   │
│  Daily: Trustpilot review monitor                │
└───────────────┬─────────────────────────────────┘
                │
    ┌───────────▼───────────┐
    │     SCANNER ENGINE     │
    │  Reddit API │ Web      │
    │  Scraping   │ Search   │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │   SIGNAL PROCESSOR     │
    │  Dedup │ Classify │    │
    │  Filter by recency     │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │   SLACK INTEGRATION    │
    │  Format │ Post │ Tag   │
    └───────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- Slack workspace with a bot token
- Reddit API credentials (free)

### 1. Clone & Install

```bash
git clone https://github.com/SplitStay/social-listener.git
cd social-listener
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run

```bash
# Run a single country scan
python -m src.scanner --country spain

# Run the Trustpilot monitor
python -m src.trustpilot

# Start the scheduler (runs all scans on schedule)
python -m src.scheduler
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | ✅ | Slack bot OAuth token |
| `SLACK_CHANNEL_ID` | ✅ | Channel to post signals (default: `#social-listening-tool`) |
| `REDDIT_CLIENT_ID` | ✅ | Reddit API app client ID |
| `REDDIT_CLIENT_SECRET` | ✅ | Reddit API app client secret |
| `REDDIT_USER_AGENT` | ✅ | Reddit API user agent string |
| `TRUSTPILOT_URL` | ❌ | Trustpilot page URL (default: splitstay.travel) |
| `DARWIN_SLACK_ID` | ❌ | Slack user ID to tag on signals |
| `SCAN_CRON_DAY` | ❌ | Day of month to scan (default: 15) |
| `SCAN_CRON_HOUR` | ❌ | Hour (UTC) to start scans (default: 7) |

### Country Configs

Each country has a JSON config in `config/`:

```json
{
  "country": "spain",
  "country_emoji": "🇪🇸",
  "events": [...],
  "platforms": [...],
  "date_range": {
    "start": "2026-06-12",
    "end": "2027-06-30"
  }
}
```

## Project Structure

```
social-listener/
├── src/
│   ├── __init__.py
│   ├── scanner.py          # Main scanning engine
│   ├── platforms/
│   │   ├── __init__.py
│   │   ├── reddit.py       # Reddit API scanner
│   │   ├── twitter.py      # X/Twitter scanner
│   │   ├── facebook.py     # Facebook group scanner
│   │   ├── web_search.py   # General web search fallback
│   │   └── trustpilot.py   # Trustpilot review scraper
│   ├── processor.py        # Signal classification & dedup
│   ├── slack_bot.py        # Slack message formatting & posting
│   ├── scheduler.py        # APScheduler cron management
│   ├── brand_monitor.py    # Brand & competitor monitoring
│   ├── price_monitor.py    # Accommodation price spike alerts
│   └── models.py           # Data models
├── config/
│   ├── spain.json
│   ├── uk.json
│   ├── us.json
│   ├── brazil.json
│   ├── germany.json
│   ├── taiwan.json
│   ├── china.json
│   └── portugal.json
├── data/
│   └── state/              # Scan state files (auto-created)
├── tests/
│   └── test_scanner.py
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Deployment

### Docker (recommended)

```bash
docker-compose up -d
```

### Railway / Render

1. Push to GitHub
2. Connect repo to Railway/Render
3. Set environment variables
4. Deploy — scheduler starts automatically

## Schedule

| Scan | Schedule | Description |
|------|----------|-------------|
| Country scans (×8) | 15th monthly, 7:00–8:10 UTC | All 8 countries staggered |
| Brand & Competitor | 15th monthly, 8:20 UTC | SplitStay mentions + competitors |
| Price Spikes | 15th monthly, 8:30 UTC | Accommodation price alerts |
| Trustpilot | Daily, 8:00 UTC | New review monitor |

## License

Private — SplitStay © 2026
