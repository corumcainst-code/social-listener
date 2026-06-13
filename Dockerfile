FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy application
COPY . .

# Create data directory
RUN mkdir -p data/state

# Smart entrypoint:
# - On Apify: run one immediate scan and finish
# - Elsewhere: run the long-lived scheduler
CMD ["python", "-m", "src.entrypoint"]
