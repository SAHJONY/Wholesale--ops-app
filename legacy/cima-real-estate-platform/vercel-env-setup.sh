#!/bin/bash
# vercel-env-setup.sh
# Script to help automate Vercel environment variable setup
# Requires Vercel CLI authentication first

echo "Vercel Environment Variable Setup Script"
echo "========================================"
echo ""

# Check if Vercel CLI is authenticated
echo "Checking Vercel authentication..."
if ! command -v vercel &> /dev/null; then
    echo "Vercel CLI not found. Installing..."
    npm install -g vercel
fi

# Try to check authentication status
if ! vercel whoami &> /dev/null; then
    echo "❌ Not authenticated with Vercel"
    echo "Please run: vercel login"
    echo "Then run this script again"
    exit 1
fi

echo "✅ Authenticated with Vercel"
echo ""

# Environment variables to add
ENV_VARS=(
    "COMPANY_NAME=SAHJONY CAPITAL LLC"
    "COMPANY_DOMAINS=www.sahjonycapital.com,sahjonycapital.com"
    "COMPANY_PHONE=+16783466284"
    "COMPANY_EMAIL=sahjonycapitalllc@outlook.com"
    "HERMES_API_URL=http://127.0.0.1:8642"
    "HERMES_DASHBOARD_URL=http://127.0.0.1:9119"
    "BLAND_API_URL=https://api.bland.ai/v1"
    "BLAND_BALANCE_ENDPOINT=https://api.bland.ai/v1/balance"
    "BLAND_CALL_ENDPOINT=https://api.bland.ai/v1/call"
    "BUSINESS_NAME=SAHJONY CAPITAL LLC"
    "BUSINESS_PERSONA=Alex Smith"
    "BUSINESS_PHONE=+16783466284"
    "BUSINESS_EMAIL=sahjonycapitalllc@outlook.com"
)

# Sensitive variables (will prompt for values)
SENSITIVE_VARS=(
    "BLAND_API_KEY"
    "SUPABASE_URL"
    "SUPABASE_ANON_KEY"
)

echo "Adding environment variables to Vercel project..."
echo ""

# Add non-sensitive variables
for var in "${ENV_VARS[@]}"; do
    echo "Adding: $var"
    if vercel env add "$var" --yes; then
        echo "✅ Added successfully"
    else
        echo "❌ Failed to add"
    fi
echo ""
done

# Prompt for sensitive variables
for var in "${SENSITIVE_VARS[@]}"; do
    echo "Please enter value for $var:"
    read -s value
    echo ""
    echo "Adding $var (value hidden)..."
    if vercel env add "$var=$value" --yes; then
        echo "✅ Added successfully"
    else
        echo "❌ Failed to add"
    fi
    echo ""
done

echo "Environment variable setup complete!"
echo ""
echo "Next steps:"
echo "1. Trigger a new deployment: vercel --prod"
echo "2. Check the dashboard for integration status"
echo "3. Test platform functionality"
echo ""

# Optional: Trigger redeployment
read -p "Trigger redeployment now? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Triggering redeployment..."
    vercel --prod
fi