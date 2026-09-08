import { Hono } from 'hono'
import { serve } from '@hono/node-server'
import { api } from './api'

const app = new Hono()

// Mount API routes
app.route('/api', api)

// Health endpoint
app.get('/health', (c) => {
  return c.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    service: 'Hermes Workspace - Real Estate Wholesale Platform',
    version: '1.0.0'
  })
})

// Serve static files in production
if (process.env.NODE_ENV === 'production') {
  app.use('*', async (c) => {
    return c.text('Hermes Workspace Real Estate Platform')
  })
}

const port = process.env.PORT ? parseInt(process.env.PORT) : 3002

console.log(`🚀 Real Estate Wholesale Platform API server running on port ${port}`)
console.log(`📊 Bland.ai Integration: ${process.env.BLAND_API_KEY ? 'Configured' : 'Not configured'}`)
console.log(`🏢 Business: ${process.env.BUSINESS_NAME || 'SAHJONY CAPITAL LLC'}`)

serve({
  fetch: app.fetch,
  port
})