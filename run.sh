#!/bin/bash

# Exit on any error
set -e

echo "🔨 Building Docker image..."
docker build -t 153-proj .

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo "🚀 Running container..."
    docker run --rm -ti 153-proj
else
    echo "❌ Build failed!"
    exit 1
fi