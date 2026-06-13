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

```text
┌─────────────────────────────────────────────────┐
│                   SCHEDULER                      │
│  Monthly: Country + Brand + Price scans          │
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
- Reddit API credentials

### 1. Clone & Install

```bash
git clone https://github.com/corumcainst-code/social-listener.git
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

# Start the scheduler
python -m src.scheduler
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | ✅ | Slack bot OAuth token |
| `SLACK_CHANNEL_ID` | ✅ | Slack channel ID, e.g. `C0123456789`. Do not use the visible channel name. |
| `REDDIT_CLIENT_ID` | ✅ | Reddit API app client ID |
| `REDDIT_CLIENT_SECRET` | ✅ | Reddit API app client secret |
| `REDDIT_USER_AGENT` | ✅ | Reddit API user agent string |
| `TRUSTPILOT_URL` | ❌ | Trustpilot page URL |
| `DARWIN_SLACK_ID` | ❌ | Slack user ID to tag on signals |
| `SCAN_CRON_DAY` | ❌ | Day of month to scan, default `15` |
| `SCAN_CRON_HOUR` | ❌ | Hour UTC to start scans, default `7` |

### Country Configs

Each country has a JSON config in `config/`:

```json
{
  "country": "spain",
  "country_emoji": "🇪🇸",
  "events": [],
  "platforms": [],
  "date_range": {
    "start": "2026-06-12",
    "end": "2027-06-30"
  }
}
```

## Project Structure

```text
social-listener/
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   ├── __init__.py
│   ├── scanner.py
│   ├── platforms/
│   ├── processor.py
│   ├── slack_bot.py
│   ├── scheduler.py
│   ├── brand_monitor.py
│   ├── price_monitor.py
│   └── models.py
├── config/
├── data/
│   └── state/
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Deployment

### Docker

```bash
docker-compose up -d
```

### Railway / Render

1. Push to GitHub.
2. Connect the repo to Railway or Render.
3. Set environment variables in the hosting platform.
4. Deploy using the scheduler command:

```bash
python -m src.scheduler
```

## Schedule

| Scan | Schedule | Description |
|------|----------|-------------|
| Country scans ×8 | 15th monthly, 07:00–08:10 UTC by default | All 8 countries staggered |
| Brand & Competitor | 15th monthly, 08:20 UTC by default | SplitStay mentions + competitors |
| Price Spikes | 15th monthly, 08:30 UTC by default | Accommodation price alerts |
| Trustpilot | Daily, 08:00 UTC | New review monitor |

## Reliability notes

- The scheduler uses one asyncio event loop so scheduled jobs stay attached to the loop that is kept alive.
- New signal URLs are only marked as known after Slack confirms all signals in the batch were posted.
- If Slack credentials are missing or posting fails, state is not updated, so leads can be retried.

## License

Private — SplitStay © 2026
