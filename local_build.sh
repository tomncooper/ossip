#!/usr/bin/env bash
set -e

RENDER_MODE=false

# Parse arguments
if [[ "$1" == "--render-only" ]]; then
    RENDER_MODE=true
    echo "🚀 Starting render-only build (HTML regeneration only)..."
else
    echo "🚀 Starting full build process..."
fi

if [[ "$RENDER_MODE" == false ]]; then
    # Install dependencies
    echo "📦 Installing dependencies with uv..."
    uv sync

    # Update KIP data (incremental)
    echo "🔄 Updating KIP data..."
    uv run python ipper/main.py kafka update

    # Download and process FLIP data
    echo "📥 Downloading and processing FLIP data..."
    uv run python ipper/main.py flink wiki download --update --refresh-days 60
fi

# Copy static page to site_files
echo "📋 Copying static files..."
mkdir -p site_files
cp templates/index.html site_files/
cp templates/style.css site_files/
cp -r templates/assets site_files/assets

# Build the Kafka site
echo "🏗️  Building Kafka site..."
uv run python ipper/main.py kafka output standalone cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips

# Build the Flink site
echo "🏗️  Building Flink site..."
uv run python ipper/main.py flink output cache/flip_wiki_cache.json site_files/flink.html site_files/flips

echo "✅ Build complete! Output in site_files/"
