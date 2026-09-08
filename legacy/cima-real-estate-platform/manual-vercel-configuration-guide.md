# Manual Vercel Environment Variables Configuration Guide

## Current Status: Platform Deployed but Missing Critical Environment Variables

**Project URL**: https://wholesale-ops-7i7l32jc8-juan-gonzalezs-projects-94b6dfe9.vercel.app

## Issues Detected on Live Platform:
1. ✅ Platform deployed successfully
2. ⚠️ Supabase database connection inactive (CRM functionality limited)
3. ⚠️ Bland.ai API integration inactive (call automation unavailable)
4. ⚠️ Hermes agent connectivity needs configuration

## Required Environment Variables

### Category 1: Company Configuration (Highest Priority)
```env
COMPANY_NAME="SAHJONY CAPITAL LLC"
COMPANY_DOMAINS="www.sahjonycapital.com,sahjonycapital.com"
COMPANY_PHONE="+16783466284"
COMPANY_EMAIL="sahjonycapitalllc@outlook.com"
```

### Category 2: Hermes Agent Configuration
```env
HERMES_API_URL="http://127.0.0.1:8642"
HERMES_DASHBOARD_URL="http://127.0.0.1:9119"
```

### Category 3: Bland.ai Integration (Call Automation)
```env
BLAND_API_KEY="[Your Bland.ai API Key]"
BLAND_API_URL="https://api.bland.ai/v1"
BLAND_BALANCE_ENDPOINT="https://api.bland.ai/v1/balance"
BLAND_CALL_ENDPOINT="https://api.bland.ai/v1/call"
```

### Category 4: CRM Database (Supabase)
```env
SUPABASE_URL="[Your Supabase Project URL]"
SUPABASE_ANON_KEY="[Your Supabase Anon Key]"
```

## Step-by-Step Manual Configuration

### Option A: Vercel Dashboard (Recommended)

1. **Navigate to Vercel Dashboard**
   - Go to https://vercel.com
   - Login with your GitHub account
   - Select the "wholesale-ops-7i7l32jc8-juan-gonzalezs-projects-94b6dfe9" project

2. **Add Environment Variables**
   - Go to Settings → Environment Variables
   - Add each variable from the lists above
   - For sensitive keys (BLAND_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY), mark as "Production"

3. **Trigger Redeployment**
   - Go to Deployments tab
   - Click "Redeploy" on the latest deployment

### Option B: GitHub Repository Secrets + Actions

1. **Add Secrets to GitHub Repository**
   - Go to your GitHub repository settings
   - Navigate to Secrets and variables → Actions
   - Add all environment variables as repository secrets

2. **Create GitHub Actions Workflow**
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
            SUPABASE_URL=${{ secrets.SUPABASE_URL }}
            SUPABASE_ANON_KEY=${{ secrets.SUPABASE_ANON_KEY }}
```

## API Key Acquisition Instructions

### 1. Bland.ai API Key
- Visit: https://bland.ai
- Create account or login
- Navigate to API Keys section
- Generate new API key
- Current balance should show $55.16

### 2. Supabase Database
- Visit: https://supabase.com
- Create new project
- Copy Project URL and Anon Key from project settings
- Set up tables for CRM functionality

### 3. Hermes Agent
- Ensure Hermes agent is running locally on port 8642
- For production, consider deploying Hermes agent separately

## Verification Steps After Configuration

1. **Check Dashboard Status**
   - Data Mode should show "ACTIVE" instead of "LOCAL"
   - Bland Balance should show current balance ($55.16)
   - Supabase connection should be active

2. **Test Functionality**
   - Lead intake form should save to database
   - AI Call functionality should work
   - CRM features should be fully operational

3. **Monitor Integration Status**
   - All "Unavailable" statuses should change to "Active"
   - Balance monitoring should update automatically

## Troubleshooting

### Common Issues:
- **Build failures**: Check environment variable syntax
- **API connectivity**: Verify API keys are correct
- **Database connection**: Ensure Supabase project is active
- **Hermes agent**: Verify agent is running and accessible

### Force Refresh:
- Clear browser cache
- Hard refresh (Ctrl+F5)
- Trigger new deployment

## Next Steps After Environment Variables Setup

1. Configure custom domain "sahjonycapital.com"
2. Set up SSL certificates
3. Configure monitoring and analytics
4. Implement backup and recovery procedures

## Support Resources
- Vercel Documentation: https://vercel.com/docs
- Supabase Documentation: https://supabase.com/docs
- Bland.ai Documentation: https://bland.ai/docs
- Hermes Agent Documentation: https://hermes-workspace.com/docs