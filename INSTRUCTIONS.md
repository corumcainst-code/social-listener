# SplitStay Social Listener — GitHub Fix Pack

This ZIP is designed to be dropped into the root of the GitHub repo:

corumcainst-code/social-listener

## What this fixes

1. src/scheduler.py
   - Uses one asyncio event loop.
   - Avoids starting APScheduler on one loop and keeping a different loop alive.
   - Adds replace_existing=True to avoid duplicate job IDs after reloads.

2. src/processor.py
   - Deduplicates and filters signals but does not immediately mark them as known.
   - Adds mark_posted(), which is used only after Slack confirms successful posting.

3. src/scanner.py
   - Only marks signals as known after every new signal in the batch is confirmed posted to Slack.
   - If Slack credentials are missing or posting partly fails, state is not updated so the signal can be retried.

4. .env.example
   - Adds the missing example environment file.
   - Keeps all secrets blank.

5. .github/workflows/ci.yml
   - Adds a GitHub Actions CI check.
   - Installs dependencies, compiles the source, and imports core modules on every push/PR.

6. README.md
   - Corrects the clone URL to corumcainst-code/social-listener.
   - Clarifies that SLACK_CHANNEL_ID should be the actual Slack channel ID, not just the visible channel name.

## How to upload through the GitHub website

1. Open GitHub.
2. Go to corumcainst-code/social-listener.
3. Click Code.
4. Click Add file.
5. Click Upload files.
6. Drag the CONTENTS of this ZIP into the upload area, not the ZIP itself.
7. GitHub should show these paths:
   - src/scheduler.py
   - src/processor.py
   - src/scanner.py
   - .env.example
   - .github/workflows/ci.yml
   - README.md
8. Scroll down to Commit changes.
9. Use this commit message:
   Harden scheduler, state handling, and CI
10. Commit directly to main, or create a new branch if GitHub suggests it.

## After uploading

1. Go to the Actions tab.
2. Open the CI run.
3. Confirm it passes.
4. Then run a manual deployed scan:
   python -m src.scanner --country uk
5. Check Slack/Viktor receives the scan output.
6. Then restart/redeploy the scheduler service:
   python -m src.scheduler

## Do not upload secrets

Do not put real Slack tokens, Reddit secrets, or API keys into .env.example.
Real values belong in your deployment platform environment variables.
