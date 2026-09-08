#!/bin/bash

# Deploy Hermes Workspace with Lobsterboard UI
cd /root/.hermes/hermes-agent/hermes-workspace

# Build the project
npm run build

# Check if vercel is installed
if command -v vercel &> /dev/null; then
    echo "Deploying with Vercel CLI..."
    vercel --prod --yes
else
    echo "Vercel CLI not found. Installing..."
    npm install -g vercel
    vercel --prod --yes
fi

echo "Deployment complete!"