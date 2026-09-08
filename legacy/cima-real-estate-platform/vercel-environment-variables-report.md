# Vercel Environment Variables Configuration Report

## Project: Sahjony Capital LLC Real Estate Wholesale Platform
**Current Deployment URL**: https://wholesale-ops-7i7l32jc8-juan-gonzalezs-projects-94b6dfe9.vercel.app

## Required Environment Variables

### 1. Company Configuration
```env
COMPANY_NAME="SAHJONY CAPITAL LLC"
COMPANY_DOMAINS="www.sahjonycapital.com,sahjonycapital.com"
COMPANY_PHONE="+167****6284"
COMPANY_EMAIL="sahjonycapitalllc@outlook.com"
```

### 2. Hermes Agent Configuration
```env
HERMES_API_URL="http://127.0.0.1:8642"
HERMES_DASHBOARD_URL="http://127.0.0.1:9119"
# HERMES_API_TOKEN="***" (Optional - only if gateway has API_SERVER_KEY set)
# HERMES_AGENT_PATH="/path/to/hermes-agent" (Optional - auto-detected)
```

### 3. Bland.ai Integration (Real Estate Call Automation)
```env
BLAND_API_KEY="your_bland_api_key_here"
BLAND_API_URL="https://api.bland.ai/v1"
BLAND_BALANCE_ENDPOINT="https://api.bland.ai/v1/balance"
BLAND_CALL_ENDPOINT="https://api.bland.ai/v1/call"
```

### 4. Business Configuration
```env
BUSINESS_NAME="SAHJONY CAPITAL LLC"
BUSINESS_PERSONA="Alex Smith"
BUSINESS_PHONE="+167****6284"
BUSINESS_EMAIL="sahjonycapitalllc@outlook.com"
```

### 5. OpenClaw AI Integration (Optional)
```env
OPENCLAW_API_KEY="your_openclaw_api_key_here"
OPENCLAW_API_URL="https://api.openclaw.ai/v1"
```

### 6. CRM Database Configuration
```env
SUPABASE_URL="your_supabase_url_here"
SUPABASE_ANON_KEY="your_supabase_key_here"
```

### 7. LLM Provider Configuration (Pick ONE)
```env
# ANTHROPIC_API_KEY="***" (Claude)
# OPENAI_API_KEY="***" (GPT)
# OPENROUTER_API_KEY="***" (Multiple models)
# GOOGLE_API_KEY="***" (Gemini)
# No key needed for Ollama/local models
```

## Vercel Project Settings

### Build Configuration
- **Framework**: TanStack Start SSR
- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Install Command**: `npm install`

### Runtime Configuration
- **Node.js Version**: (Auto-detected)
- **Serverless Functions**: Enabled
- **Static Assets**: Enabled

## Steps to Add Environment Variables

### Option 1: Vercel Dashboard
1. Navigate to https://vercel.com
2. Select the "wholesale-ops-7i7l32jc8-juan-gonzalezs-projects-94b6dfe9" project
3. Go to Settings → Environment Variables
4. Add each variable from the list above
5. Redeploy the project

### Option 2: Vercel CLI
```bash
# Install Vercel CLI globally
npm i -g vercel

# Login to Vercel
vercel login

# Navigate to project directory
cd /root/.hermes/hermes-agent/hermes-workspace

# Add environment variables one by one
vercel env add COMPANY_NAME
vercel env add COMPANY_DOMAINS
vercel env add COMPANY_PHONE
vercel env add COMPANY_EMAIL
vercel env add HERMES_API_URL
vercel env add HERMES_DASHBOARD_URL
# ... continue with remaining variables

# Deploy with new environment variables
vercel --prod
```

### Option 3: GitHub Actions (Recommended)
Add a GitHub Actions workflow that automatically deploys to Vercel with environment variables:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Vercel
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci && npm run build
      - uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          vercel-args: '--prod'
          vercel-env: |
            COMPANY_NAME=${{ secrets.COMPANY_NAME }}
            COMPANY_DOMAINS=${{ secrets.COMPANY_DOMAINS }}
            COMPANY_PHONE=${{ secrets.COMPANY_PHONE }}
            COMPANY_EMAIL=${{ secrets.COMPANY_EMAIL }}
            HERMES_API_URL=${{ secrets.HERMES_API_URL }}
            HERMES_DASHBOARD_URL=${{ secrets.HERMES_DASHBOARD_URL }}
            BLAND_API_KEY=${{ secrets.BLAND_API_KEY }}
            BLAND_API_URL=${{ secrets.BLAND_API_URL }}
            BUSINESS_NAME=${{ secrets.BUSINESS_NAME }}
            BUSINESS_PERSONA=${{ secrets.BUSINESS_PERSONA }}
            BUSINESS_PHONE=${{ secrets.BUSINESS_PHONE }}
            BUSINESS_EMAIL=${{ secrets.BUSINESS_EMAIL }}
```

## Important Notes

1. **Security**: Sensitive API keys should be stored as secrets, not in environment files
2. **Build Optimization**: Vercel caches builds - trigger rebuild after adding variables
3. **Hermes Agent**: Ensure Hermes agent is running for API connectivity
4. **Custom Domain**: Configure custom domain "sahjonycapital.com" after deployment

## Verification Steps

After adding environment variables:
1. Trigger a new deployment
2. Verify the platform loads correctly
3. Check company branding appears
4. Test Hermes agent connectivity
5. Validate Bland.ai integration

## Current Project Status
- ✅ Platform deployed to Vercel
- ✅ TanStack Start SSR configured
- ✅ Company branding configured
- ⚠️ Environment variables need to be added
- ⚠️ Hermes agent connectivity needs configuration
- ⚠️ Bland.ai integration requires API keys

## Next Steps
1. Add all environment variables to Vercel project
2. Redeploy to apply changes
3. Configure custom domain
4. Test platform functionality
5. Set up continuous deployment pipeline