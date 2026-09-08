import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

interface BalanceData {
  ok: boolean
  bland: {
    ok: boolean
    currentBalance: number
    raw: any
  }
  openclawApiKey: {
    ok: boolean
    message: string
  }
  ts: string
}

interface SnapshotData {
  ok: boolean
  business: string
  persona: string
  policy: {
    transferCallsToOwner: boolean
    objective: string
  }
  balances: {
    bland: any
    openclaw: any
  }
  connectors: Array<{
    name: string
    status: string
  }>
  timestamp: string
}

export function RealEstateDashboard() {
  const [balanceData, setBalanceData] = useState<BalanceData | null>(null)
  const [snapshotData, setSnapshotData] = useState<SnapshotData | null>(null)
  const [loading, setLoading] = useState(true)
  const [callForm, setCallForm] = useState({
    propertyAddress: '',
    phoneNumber: '',
    ownerName: ''
  })

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 45000) // Refresh every 45 seconds
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      const [balanceRes, snapshotRes] = await Promise.all([
        fetch('/api/monitor/balance'),
        fetch('/api/control/snapshot')
      ])

      if (balanceRes.ok) {
        const balanceData = await balanceRes.json()
        setBalanceData(balanceData)
      }

      if (snapshotRes.ok) {
        const snapshotData = await snapshotRes.json()
        setSnapshotData(snapshotData)
      }
    } catch (error) {
      console.error('Error fetching data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCallInitiation = async () => {
    if (!callForm.propertyAddress || !callForm.phoneNumber) {
      alert('Please fill in property address and phone number')
      return
    }

    try {
      const response = await fetch('/api/call/initiate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(callForm)
      })

      if (response.ok) {
        const result = await response.json()
        alert(`Call initiated successfully! Call ID: ${result.callId}`)
        setCallForm({ propertyAddress: '', phoneNumber: '', ownerName: '' })
      } else {
        alert('Failed to initiate call')
      }
    } catch (error) {
      console.error('Error initiating call:', error)
      alert('Call initiation failed')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-gray-900"></div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      {/* Header */}
      <div className="border-b border-white/20">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-white">
                Premium Wholesale Operating System
              </h1>
              <p className="text-zinc-300 mt-2">
                {snapshotData?.business || 'SAHJONY CAPITAL LLC'} • PHASE 3
              </p>
            </div>
            <div className="text-right">
              <p className="text-zinc-300">Data Mode: <span className="font-semibold uppercase">LOCAL</span></p>
              <p className="text-zinc-300">OpenClaw Brain: <span className="font-semibold uppercase text-green-400">CONNECTED</span></p>
              <p className="text-zinc-300">Paperclip Skill: <span className="font-semibold uppercase">ENABLED VIA CONSOLE COMMAND PREFIX</span></p>
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="sticky top-2 z-20">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex flex-wrap gap-2">
            <a href="#overview" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Overview
            </a>
            <a href="#enterprise" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Enterprise
            </a>
            <a href="#intake" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Intake
            </a>
            <a href="#tracker" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Tracker
            </a>
            <a href="#automation" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Automation
            </a>
            <a href="#console" className="px-3 py-2 rounded-lg border border-white/20 hover:bg-white/10 text-white">
              Console
            </a>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* National Command Center Snapshot */}
        <Card id="overview">
          <CardHeader>
            <CardTitle className="text-xl font-semibold">National Command Center Snapshot</CardTitle>
            <p className="text-sm text-zinc-300">30s auto-refresh. Central view for balance, policy, connectors, and operating status.</p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-white/15 bg-black/20 p-4">
                <p className="text-xs text-zinc-300">Business</p>
                <p className="mt-1 font-semibold">{snapshotData?.business || 'SAHJONY CAPITAL LLC'}</p>
                <p className="mt-1 text-xs text-zinc-400">Voice: {snapshotData?.persona || 'Alex Smith'}</p>
              </div>
              <div className="rounded-xl border border-white/15 bg-black/20 p-4">
                <p className="text-xs text-zinc-300">Bland Balance</p>
                <p className="mt-1 text-2xl font-bold text-emerald-300">
                  ${balanceData?.bland?.currentBalance?.toFixed(2) || 'Unavailable'}
                </p>
              </div>
              <div className="rounded-xl border border-white/15 bg-black/20 p-4">
                <p className="text-xs text-zinc-300">OpenClaw / OpenAI</p>
                <p className="mt-1 text-sm text-zinc-200">Monitoring active</p>
              </div>
            </div>
            
            <div className="mt-4 rounded-xl border border-white/15 bg-black/20 p-4 text-xs text-zinc-300">
              <p className="font-semibold">Connectors:</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {snapshotData?.connectors?.map((connector, index) => (
                  <Badge key={index} variant="secondary" className="text-xs">
                    {connector.name}
                  </Badge>
                )) || 'Loading...'}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Live Balance Monitor */}
        <Card>
          <CardHeader>
            <CardTitle className="text-xl font-semibold">Live Balance Monitor</CardTitle>
            <p className="text-sm text-zinc-300">Auto-refresh every 45 seconds for operating cash visibility.</p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-white/15 bg-black/20 p-4">
                <p className="text-sm font-semibold">Bland.ai Call Balance</p>
                <p className="mt-1 text-2xl font-bold text-emerald-300">
                  ${balanceData?.bland?.currentBalance?.toFixed(2) || 'Unavailable'}
                </p>
                <p className="mt-1 text-xs text-zinc-400">
                  Updated: {balanceData?.ts ? new Date(balanceData.ts).toLocaleString() : 'Waiting for update...'}
                </p>
              </div>
              <div className="rounded-xl border border-white/15 bg-black/20 p-4">
                <p className="text-sm font-semibold">OpenClaw API Key Balance</p>
                <p className="mt-1 text-2xl font-bold text-sky-300">
                  {balanceData?.openclawApiKey?.ok ? 'Available' : 'Unavailable'}
                </p>
                <p className="mt-1 text-sm text-amber-200">
                  {balanceData?.openclawApiKey?.message || 'Integration pending'}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* AI Call Section */}
        <Card id="automation">
          <CardHeader>
            <CardTitle className="text-xl font-semibold">AI Call Section (Active)</CardTitle>
            <p className="text-sm text-zinc-300">Direct Bland activation for outbound seller calls.</p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              <Input
                placeholder="Property address"
                value={callForm.propertyAddress}
                onChange={(e) => setCallForm({...callForm, propertyAddress: e.target.value})}
                className="rounded-xl border border-white/20 bg-black/30 px-3 py-2 text-sm"
              />
              <Input
                placeholder="Phone number (E.164, e.g. +1678...)"
                value={callForm.phoneNumber}
                onChange={(e) => setCallForm({...callForm, phoneNumber: e.target.value})}
                className="rounded-xl border border-white/20 bg-black/30 px-3 py-2 text-sm"
              />
              <Input
                placeholder="Owner name (optional)"
                value={callForm.ownerName}
                onChange={(e) => setCallForm({...callForm, ownerName: e.target.value})}
                className="rounded-xl border border-white/20 bg-black/30 px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <Button 
                  onClick={handleCallInitiation}
                  className="rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-black"
                >
                  Activate AI Call
                </Button>
                <Button 
                  variant="outline"
                  className="rounded-xl border border-emerald-300/40 px-4 py-2 text-sm font-semibold text-emerald-200"
                >
                  Call + Save + Brief
                </Button>
              </div>
            </div>
            
            <textarea 
              className="mt-4 min-h-24 w-full rounded-xl border border-white/20 bg-black/30 p-3 text-sm"
              defaultValue="You are Alex Smith, acquisitions manager at SAHJONY CAPITAL LLC. Open professionally, confirm you are discussing the correct property, then collect: seller motivation, property condition (roof/HVAC/plumbing/electrical/foundation), occupancy/vacancy, timeline to sell, asking price, lowest acceptable price, liens/title issues, and best callback time. Never transfer the call. Close by confirming next step: we review and return with a formal cash offer strategy."
            />
          </CardContent>
        </Card>

        {/* Enterprise Control Layer */}
        <Card id="enterprise">
          <CardHeader>
            <CardTitle className="text-xl font-semibold">Enterprise Control Layer</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-zinc-300">Role</span>
                <select className="rounded-lg border border-white/20 bg-black/30 px-2 py-1">
                  <option selected>CEO</option>
                  <option>ACQ</option>
                  <option>DISPO</option>
                  <option>OPS</option>
                </select>
              </div>
              <div className="flex flex-wrap gap-2 text-sm">
                <span className="rounded-lg border border-red-300/30 bg-red-500/10 px-2 py-1 text-red-200">SLA Overdue: 0</span>
                <span className="rounded-lg border border-amber-300/30 bg-amber-500/10 px-2 py-1 text-amber-200">Due Today: 0</span>
              </div>
            </div>
            
            <div className="mt-3 flex flex-wrap gap-2">
              <Button className="rounded-xl bg-fuchsia-400 px-3 py-2 text-sm font-semibold text-black">
                Generate CEO Report
              </Button>
              <Button variant="outline" className="rounded-xl border border-fuchsia-300/40 px-3 py-2 text-sm font-semibold text-fuchsia-100">
                Email CEO Report
              </Button>
            </div>
            
            <div className="mt-3 rounded-xl border border-white/15 bg-black/20 p-3">
              <p className="text-sm font-semibold">Audit Log</p>
              <div className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-zinc-300">
                <p>No events yet.</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}