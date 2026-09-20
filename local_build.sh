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
    SIP_LOG=$(mktemp)
    SHIP_LOG=$(mktemp)
    KDP_LOG=$(mktemp)

    # Clean up temp files on exit
    trap "rm -f $KIP_LOG $FLIP_LOG $SIP_LOG $SHIP_LOG $KDP_LOG" EXIT

    # Update KIP and FLIP data in parallel (both are I/O-bound),
    # plus the three GitHub-backed proposal caches (fast, incremental)
    echo "🔄 Updating KIP, FLIP and GitHub proposal data in parallel..."

    uv run python ipper/main.py kafka update > "$KIP_LOG" 2>&1 &
    KIP_PID=$!

    uv run python ipper/main.py flink wiki download --update --refresh-days 60 > "$FLIP_LOG" 2>&1 &
    FLIP_PID=$!

    uv run python ipper/main.py strimzi update > "$SIP_LOG" 2>&1 &
    SIP_PID=$!

    uv run python ipper/main.py streamshub update > "$SHIP_LOG" 2>&1 &
    SHIP_PID=$!

    uv run python ipper/main.py kroxylicious update > "$KDP_LOG" 2>&1 &
    KDP_PID=$!

    # Wait for both processes and capture exit codes
    wait $KIP_PID
    KIP_EXIT=$?
    wait $FLIP_PID
    FLIP_EXIT=$?
    wait $SIP_PID
    SIP_EXIT=$?
    wait $SHIP_PID
    SHIP_EXIT=$?
    wait $KDP_PID
    KDP_EXIT=$?

    # Display buffered output sequentially
    echo "📊 KIP Update Output:"
    cat "$KIP_LOG"
    echo ""
    echo "📊 FLIP Update Output:"
    cat "$FLIP_LOG"
    echo ""
    echo "📊 SIP Update Output:"
    cat "$SIP_LOG"
    echo ""
    echo "📊 SHIP Update Output:"
    cat "$SHIP_LOG"
    echo ""
    echo "📊 KDP Update Output:"
    cat "$KDP_LOG"
    echo ""

    # Check if either process failed
    if [ $KIP_EXIT -ne 0 ] || [ $FLIP_EXIT -ne 0 ] || [ $SIP_EXIT -ne 0 ] || [ $SHIP_EXIT -ne 0 ] || [ $KDP_EXIT -ne 0 ]; then
        echo "❌ Update failed: KIP exit code=$KIP_EXIT, FLIP exit code=$FLIP_EXIT, SIP exit code=$SIP_EXIT, SHIP exit code=$SHIP_EXIT, KDP exit code=$KDP_EXIT"
        exit 1
    fi

    echo "✅ All updates completed successfully"
fi

# Copy static page to site_files
# NOTE: 'cp -r src dst' where dst already exists nests src *inside* dst
# (site_files/assets/assets/...), leaving the previously-copied files stale.
# Copy the directory *contents* so files are overwritten on every build.
echo "📋 Copying static files..."
mkdir -p site_files
cp templates/index.html site_files/
cp templates/style.css site_files/
mkdir -p site_files/assets
cp -r templates/assets/. site_files/assets/
mkdir -p site_files/skill/ossip
cp templates/skill/ossip/SKILL.md site_files/skill/ossip/SKILL.md
cp templates/api.html site_files/api.html 2>/dev/null || true
cp templates/skills.html site_files/skills.html 2>/dev/null || true

# Build the Kafka site
echo "🏗️  Building Kafka site..."
uv run python ipper/main.py kafka output standalone cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips --api-dir site_files/api/v1/kafka

# Build the Flink site
echo "🏗️  Building Flink site..."
uv run python ipper/main.py flink output cache/flip_wiki_cache.json site_files/flink.html site_files/flips --api-dir site_files/api/v1/flink

# Build the Strimzi site
echo "🏗️  Building Strimzi site..."
uv run python ipper/main.py strimzi output cache/sip_proposals_cache.json site_files/strimzi.html site_files/sips --api-dir site_files/api/v1/strimzi

# Build the StreamsHub site
echo "🏗️  Building StreamsHub site..."
uv run python ipper/main.py streamshub output cache/ship_proposals_cache.json site_files/streamshub.html site_files/ships --api-dir site_files/api/v1/streamshub

# Build the Kroxylicious site
echo "🏗️  Building Kroxylicious site..."
uv run python ipper/main.py kroxylicious output cache/kdp_proposals_cache.json site_files/kroxylicious.html site_files/kdps --api-dir site_files/api/v1/kroxylicious

# Generate API index
echo "📋 Generating API index..."
uv run python -c "
from ipper.common.api_output import generate_api_index
from pathlib import Path
generate_api_index(Path('site_files/api/v1'))
"

echo "✅ Build complete! Output in site_files/"
