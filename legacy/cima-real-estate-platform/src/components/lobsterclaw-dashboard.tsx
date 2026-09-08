import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'

// LobsterClaw-inspired dashboard components
export function LobsterClawDashboard() {
  const [activeTab, setActiveTab] = useState('overview')

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800/50 backdrop-blur">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">SC</span>
              </div>
              <h1 className="text-2xl font-bold text-white">
                Sahjony Capital
              </h1>
              <Badge variant="secondary" className="bg-green-500/20 text-green-400">
                LIVE
              </Badge>
            </div>
            <div className="flex items-center space-x-4">
              <Button variant="outline" className="border-slate-600 text-slate-300">
                Support
              </Button>
              <Button className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700">
                Owner Login
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-6 py-8">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="grid w-full grid-cols-5 bg-slate-800/50 p-1 rounded-lg">
            <TabsTrigger value="overview" className="data-[state=active]:bg-slate-700 text-slate-300">
              Overview
            </TabsTrigger>
            <TabsTrigger value="agents" className="data-[state=active]:bg-slate-700 text-slate-300">
              AI Agents
            </TabsTrigger>
            <TabsTrigger value="properties" className="data-[state=active]:bg-slate-700 text-slate-300">
              Properties
            </TabsTrigger>
            <TabsTrigger value="tools" className="data-[state=active]:bg-slate-700 text-slate-300">
              Tools
            </TabsTrigger>
            <TabsTrigger value="owner" className="data-[state=active]:bg-slate-700 text-slate-300">
              Owner
            </TabsTrigger>
          </TabsList>

          {/* Overview Tab */}
          <TabsContent value="overview" className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-slate-300 flex items-center justify-between">
                    <span>Portfolio Value</span>
                    <Badge variant="default" className="bg-green-500/20 text-green-400">
                      +12.5%
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-bold text-white">$2.8M</p>
                  <p className="text-sm text-slate-400 mt-2">10 active properties</p>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-slate-300">AI Agents Active</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-bold text-white">6/6</p>
                  <p className="text-sm text-slate-400 mt-2">All systems operational</p>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-slate-300">Call Balance</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-bold text-white">$55.16</p>
                  <p className="text-sm text-slate-400 mt-2">Bland.ai credits available</p>
                </CardContent>
              </Card>
            </div>

            {/* Recent Activity */}
            <Card className="bg-slate-800/50 border-slate-700">
              <CardHeader>
                <CardTitle className="text-slate-300">Recent Activity</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="flex items-center justify-between p-3 bg-slate-700/30 rounded">
                    <div className="flex items-center space-x-3">
                      <div className="w-2 h-2 bg-green-400 rounded-full"></div>
                      <span className="text-slate-300">Property analysis completed</span>
                    </div>
                    <span className="text-slate-400 text-sm">2 min ago</span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-slate-700/30 rounded">
                    <div className="flex items-center space-x-3">
                      <div className="w-2 h-2 bg-blue-400 rounded-full"></div>
                      <span className="text-slate-300">Lead qualification call made</span>
                    </div>
                    <span className="text-slate-400 text-sm">15 min ago</span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-slate-700/30 rounded">
                    <div className="flex items-center space-x-3">
                      <div className="w-2 h-2 bg-purple-400 rounded-full"></div>
                      <span className="text-slate-300">Deal matched with investor</span>
                    </div>
                    <span className="text-slate-400 text-sm">1 hour ago</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* AI Agents Tab */}
          <TabsContent value="agents" className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[
                { name: 'Acquisition Agent', status: 'active', description: 'Automated property sourcing' },
                { name: 'Disposition Agent', status: 'active', description: 'Buyer outreach & marketing' },
                { name: 'Cash Buyers Agent', status: 'active', description: 'Deal matching with investors' },
                { name: 'Property Analysis', status: 'active', description: 'ROI calculations & valuation' },
                { name: 'Call Automation', status: 'active', description: 'AI-powered lead generation' },
                { name: 'CRM Integration', status: 'active', description: 'Portfolio management' }
              ].map((agent, index) => (
                <Card key={index} className="bg-slate-800/50 border-slate-700">
                  <CardHeader>
                    <CardTitle className="text-slate-300 flex items-center justify-between">
                      <span>{agent.name}</span>
                      <Badge variant={agent.status === 'active' ? 'default' : 'secondary'} 
                             className={agent.status === 'active' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}>
                        {agent.status}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-slate-400 text-sm">{agent.description}</p>
                    <Button variant="outline" className="w-full mt-4 border-slate-600 text-slate-300">
                      Configure
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* Tools Tab */}
          <TabsContent value="tools" className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[
                { name: 'ANA', description: 'Advanced Neural Analytics', status: 'ready' },
                { name: 'CLAW3D', description: '3D Property Modeling', status: 'ready' },
                { name: 'Mirofish', description: 'Visual Collaboration', status: 'ready' },
                { name: 'Paperclip', description: 'Document Processing', status: 'ready' },
                { name: 'Claude Code', description: 'AI Coding Assistant', status: 'ready' },
                { name: 'Kali Linux', description: 'Security Suite', status: 'ready' }
              ].map((tool, index) => (
                <Card key={index} className="bg-slate-800/50 border-slate-700">
                  <CardHeader>
                    <CardTitle className="text-slate-300">{tool.name}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-slate-400 text-sm mb-4">{tool.description}</p>
                    <Button className="w-full bg-gradient-to-r from-blue-600 to-purple-600">
                      Launch Tool
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

            {/* Owner Tab */}
            <TabsContent value="owner" className="space-y-6">
              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-slate-300">Owner Authentication</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <p className="text-slate-400">Owner access requires authentication token</p>
                    <Button className="w-full bg-gradient-to-r from-blue-600 to-purple-600">
                      Authenticate
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
        </Tabs>
      </main>
    </div>
  )
}