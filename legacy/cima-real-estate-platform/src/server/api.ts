import { Hono } from 'hono'
import { cors } from 'hono/cors'

export const api = new Hono()

// Enable CORS for frontend
api.use('*', cors())

// Bland.ai Balance Monitoring
api.get('/monitor/balance', async (c) => {
  try {
    const blandResponse = await fetch('https://api.bland.ai/v1/balance', {
      headers: {
        'Authorization': `Bearer ${process.env.BLAND_API_KEY}`,
        'Content-Type': 'application/json'
      }
    })

    if (!blandResponse.ok) {
      return c.json({
        ok: false,
        message: 'Failed to fetch Bland.ai balance',
        error: await blandResponse.text()
      }, 500)
    }

    const blandData = await blandResponse.json()

    // OpenClaw/OpenAI balance check (optional)
    let openclawData = null
    if (process.env.OPENCLAW_API_KEY) {
      try {
        const openaiResponse = await fetch('https://api.openai.com/v1/usage', {
          headers: {
            'Authorization': `Bearer ${process.env.OPENCLAW_API_KEY}`
          }
        })

        if (openaiResponse.ok) {
          openclawData = await openaiResponse.json()
        } else {
          openclawData = {
            ok: false,
            message: 'OpenAI balance endpoint did not return spend; verify key permissions.',
            error: await openaiResponse.text()
          }
        }
      } catch (error) {
        openclawData = {
          ok: false,
          message: 'OpenAI balance check failed',
          error: error.message
        }
      }
    }

    return c.json({
      ok: true,
      bland: {
        ok: true,
        currentBalance: blandData.billing?.current_balance || 0,
        raw: blandData
      },
      openclawApiKey: openclawData || {
        ok: false,
        message: 'OpenAI key not configured'
      },
      ts: new Date().toISOString()
    })
  } catch (error) {
    return c.json({
      ok: false,
      message: 'Balance monitoring failed',
      error: error.message
    }, 500)
  }
})

// Control Snapshot
api.get('/control/snapshot', async (c) => {
  const snapshot = {
    ok: true,
    business: process.env.BUSINESS_NAME || 'SAHJONY CAPITAL LLC',
    persona: process.env.BUSINESS_PERSONA || 'Alex Smith',
    policy: {
      transferCallsToOwner: false,
      objective: 'Collect full seller intel and generate callback closing briefs'
    },
    balances: {
      bland: null,
      openclaw: null
    },
    connectors: [
      { name: 'Propwire', status: 'connector-ready' },
      { name: 'PropStream', status: 'connector-ready' },
      { name: 'BatchLeads', status: 'connector-ready' },
      { name: 'Zillow', status: 'connector-ready' },
      { name: 'Realtor.com', status: 'connector-ready' },
      { name: 'Redfin', status: 'connector-ready' },
      { name: 'FSBO', status: 'connector-ready' },
      { name: 'Facebook Marketplace', status: 'connector-ready' },
      { name: 'County Records', status: 'connector-ready' }
    ],
    timestamp: new Date().toISOString()
  }

  return c.json(snapshot)
})

// Bland.ai Call Initiation
api.post('/call/initiate', async (c) => {
  try {
    const body = await c.req.json()
    const { propertyAddress, phoneNumber, ownerName, callScript } = body

    if (!propertyAddress || !phoneNumber) {
      return c.json({
        ok: false,
        message: 'Property address and phone number are required'
      }, 400)
    }

    const callData = {
      phone_number: phoneNumber,
      task: callScript || `You are ${process.env.BUSINESS_PERSONA || 'Alex Smith'}, acquisitions manager at ${process.env.BUSINESS_NAME || 'SAHJONY CAPITAL LLC'}. Open professionally, confirm you are discussing the correct property (${propertyAddress}), then collect: seller motivation, property condition (roof/HVAC/plumbing/electrical/foundation), occupancy/vacancy, timeline to sell, asking price, lowest acceptable price, liens/title issues, and best callback time. Never transfer the call. Close by confirming next step: we review and return with a formal cash offer strategy.`,
      voice: 'alex',
      reduce_latency: true,
      wait_for_greeting: true,
      record: true,
      max_duration: 300,
      model: 'enhanced',
      tools: ['web_search'],
      interruption_threshold: 0.5
    }

    const callResponse = await fetch('https://api.bland.ai/v1/calls', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.BLAND_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(callData)
    })

    if (!callResponse.ok) {
      return c.json({
        ok: false,
        message: 'Failed to initiate call',
        error: await callResponse.text()
      }, 500)
    }

    const callResult = await callResponse.json()

    return c.json({
      ok: true,
      callId: callResult.call_id,
      status: callResult.status,
      message: 'Call initiated successfully',
      callData: callResult
    })
  } catch (error) {
    return c.json({
      ok: false,
      message: 'Call initiation failed',
      error: error.message
    }, 500)
  }
})

// Lead Management API
api.post('/leads/create', async (c) => {
  try {
    const body = await c.req.json()
    const {
      propertyAddress,
      contactPhone,
      followUpDate,
      beds,
      baths,
      sqft,
      askingPrice,
      arv,
      rehabEstimate,
      notes
    } = body

    // Basic validation
    if (!propertyAddress || !contactPhone) {
      return c.json({
        ok: false,
        message: 'Property address and contact phone are required'
      }, 400)
    }

    // Calculate MAO (Maximum Allowable Offer)
    const mao = arv && rehabEstimate ? arv - rehabEstimate - (arv * 0.3) : 0

    const leadData = {
      id: Date.now().toString(),
      propertyAddress,
      contactPhone,
      followUpDate: followUpDate || new Date().toISOString().split('T')[0],
      beds: beds || 3,
      baths: baths || 2,
      sqft: sqft || 1200,
      askingPrice: askingPrice || 0,
      arv: arv || 0,
      rehabEstimate: rehabEstimate || 0,
      mao: mao,
      notes: notes || '',
      status: 'new',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }

    // TODO: Save to database
    // For now, return the created lead

    return c.json({
      ok: true,
      message: 'Lead created successfully',
      lead: leadData
    })
  } catch (error) {
    return c.json({
      ok: false,
      message: 'Lead creation failed',
      error: error.message
    }, 500)
  }
})

// Health Check
api.get('/health', (c) => {
  return c.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    service: 'Real Estate Wholesale Platform',
    version: '1.0.0'
  })
})

export default api