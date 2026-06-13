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

## ## Schedule

| Scan                                    | Schedule         | Description                                                                                                                |
| --------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Event & accommodation signals — Batch A | Daily, 07:00 UTC | Scans Spain, UK, US, and Brazil for public event, accommodation-share, room-share, group, and cost-pain signals            |
| Event & accommodation signals — Batch B | Daily, 07:30 UTC | Scans Germany, Taiwan, China, and Portugal for public event, accommodation-share, room-share, group, and cost-pain signals |
| Brand & competitor monitoring           | Future module    | Tracks SplitStay mentions and competitor-related signals                                                                   |
| Price spike monitoring                  | Future module    | Tracks accommodation price increases around priority events                                                                |
| Trustpilot monitoring                   | Future module    | Monitors new SplitStay reviews once Trustpilot is active                                                                   |

## Current monitoring coverage

The social listener currently monitors 8 priority countries:

* Spain
* United Kingdom
* United States
* Brazil
* Germany
* Taiwan
* China
* Portugal

The daily scans focus on future events and public/social-web signals where people may be looking for accommodation support, hotel sharing, room sharing, group stays, cheaper options, or event-related travel help.

Current monitored platforms include:

* Facebook
* Instagram
* TikTok
* Telegram

Reddit monitoring is prepared but remains inactive until Reddit credentials are added.

## Compliance & privacy framework

SplitStay Social Listener is designed to monitor public and searchable event/accommodation-related signals only.

The system does not:

* access private groups or locked accounts;
* bypass login walls, paywalls, robots.txt restrictions, or platform security controls;
* collect passwords, private messages, hidden comments, or sensitive personal data;
* automatically contact individuals;
* sell, export, or share personal data with third parties.

The system is designed to:

* collect only the minimum signal information needed for internal lead review;
* focus on future events, accommodation-share intent, room-share intent, group-stay intent, and event-related cost-pain signals;
* filter out irrelevant, past-event, weak, sensitive, or low-quality results;
* route qualified leads into an internal Slack channel for human review;
* keep a human decision-maker in the loop before any outreach;
* support removal, objection, and deletion requests where applicable.

Current limitations:

* The scanner only monitors public/searchable web and social signals.
* It does not access private groups, private accounts, login-only comment threads, or hidden social content.
* Reddit monitoring is prepared but inactive until valid Reddit credentials are added.
* Private-platform or logged-in data access should only be added after a formal legal/privacy review.

Before scaling, enabling automated outreach, adding private-platform credentials, or using the data for direct marketing, SplitStay should complete a formal privacy review covering the UK, EU, US, Brazil, Taiwan, China, and Portugal.


## Reliability notes

* The system runs in two daily batches to reduce timeout risk and keep the scans reliable.
* Priority events are filtered so the scanner focuses on future events rather than past events.
* The scanner looks for public/searchable event posts, group pages, social captions, discussion-style signals, and accommodation-related intent.
* Private groups, locked accounts, hidden comments, or login-only platform content may not be accessible without additional platform credentials or scraper integrations.
* New signal URLs are only marked as known after Slack confirms the batch was processed.
* If Slack posting fails, the system avoids marking those leads as completed so they can be retried.
* Qualified leads are posted into Slack with the country, platform, lead type, score, reason, suggested action, and original source link.


## License

Private - SplitStay © 2026
