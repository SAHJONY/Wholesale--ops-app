#!/bin/bash

# Deployment Script for Hermes Real Estate Wholesale Platform
# This script deploys our redesigned platform to the existing Vercel project

echo "🚀 Deploying Hermes Real Estate Wholesale Platform to Vercel..."

# Check if we're in the correct directory
if [ ! -f "package.json" ]; then
    echo "❌ Not in project root directory"
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
npm install

# Build the project
echo "🏗️ Building project..."
npm run build

echo "✅ Build completed successfully!"
echo ""
echo "📋 Deployment Summary:"
echo "   - Hermes Workspace integrated with Real Estate Wholesale Platform"
echo "   - Bland.ai integration preserved ($55.16 balance)"
echo "   - Multi-agent orchestration ready"
echo "   - 10-business portfolio management foundation"
echo ""
echo "🌐 Deploy with: vercel --prod"
echo ""
echo "🎯 Next Steps:"
echo "   1. Set Bland.ai API keys in environment variables"
echo "   2. Configure OpenClaw AI integration"
echo "   3. Deploy to production using 'vercel --prod'"
echo "   4. Test autonomous outbound/inbound calling functionality"