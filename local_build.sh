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

    # Create temporary files for buffering parallel process output
    KIP_LOG=$(mktemp)
    FLIP_LOG=$(mktemp)
    
    # Clean up temp files on exit
    trap "rm -f $KIP_LOG $FLIP_LOG" EXIT

    # Update KIP and FLIP data in parallel (both are I/O-bound)
    echo "🔄 Updating KIP and FLIP data in parallel..."
    
    uv run python ipper/main.py kafka update > "$KIP_LOG" 2>&1 &
    KIP_PID=$!
    
    uv run python ipper/main.py flink wiki download --update --refresh-days 60 > "$FLIP_LOG" 2>&1 &
    FLIP_PID=$!

    # Wait for both processes and capture exit codes
    wait $KIP_PID
    KIP_EXIT=$?
    wait $FLIP_PID
    FLIP_EXIT=$?

    # Display buffered output sequentially
    echo "📊 KIP Update Output:"
    cat "$KIP_LOG"
    echo ""
    echo "📊 FLIP Update Output:"
    cat "$FLIP_LOG"
    echo ""

    # Check if either process failed
    if [ $KIP_EXIT -ne 0 ] || [ $FLIP_EXIT -ne 0 ]; then
        echo "❌ Update failed: KIP exit code=$KIP_EXIT, FLIP exit code=$FLIP_EXIT"
        exit 1
    fi
    
    echo "✅ Both updates completed successfully"
fi

# Copy static page to site_files
echo "📋 Copying static files..."
mkdir -p site_files
cp templates/index.html site_files/
cp templates/style.css site_files/
cp -r templates/assets site_files/assets
mkdir -p site_files/skill/ossip
cp templates/skill/ossip/SKILL.md site_files/skill/ossip/SKILL.md
cp templates/api.html site_files/api.html 2>/dev/null || true

# Build the Kafka site
echo "🏗️  Building Kafka site..."
uv run python ipper/main.py kafka output standalone cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips --api-dir site_files/api/v1/kafka

# Build the Flink site
echo "🏗️  Building Flink site..."
uv run python ipper/main.py flink output cache/flip_wiki_cache.json site_files/flink.html site_files/flips --api-dir site_files/api/v1/flink

# Generate API index
echo "📋 Generating API index..."
uv run python -c "
from ipper.common.api_output import generate_api_index
from pathlib import Path
generate_api_index(Path('site_files/api/v1'))
"

echo "✅ Build complete! Output in site_files/"
