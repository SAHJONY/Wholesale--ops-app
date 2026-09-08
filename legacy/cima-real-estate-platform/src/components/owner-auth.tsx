import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const OWNER_TOKEN = "SAHJONY_CAPITAL_OWNER_2025" // Hardcoded owner token

export function OwnerAuth({ onAuth }: { onAuth: (authenticated: boolean) => void }) {
  const [token, setToken] = useState('')
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = () => {
    if (token === OWNER_TOKEN) {
      setIsAuthenticated(true)
      setError('')
      onAuth(true)
    } else {
      setError('Invalid owner token')
    }
  }

  const handleLogout = () => {
    setIsAuthenticated(false)
    setToken('')
    onAuth(false)
  }

  if (isAuthenticated) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Owner Dashboard</span>
            <Button variant="outline" size="sm" onClick={handleLogout}>
              Logout
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Welcome, Owner. You have full control over the platform.
          </p>
          <div className="space-y-4">
            <Button className="w-full">Update Hermes Agent</Button>
            <Button variant="outline" className="w-full">Manage Secrets</Button>
            <Button variant="outline" className="w-full">GitHub Integration</Button>
            <Button variant="outline" className="w-full">Email & SMS Agent</Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Owner Authentication</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <Label htmlFor="owner-token">Owner Token</Label>
            <Input
              id="owner-token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Enter owner token"
              className="mt-1"
            />
          </div>
          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}
          <Button onClick={handleLogin} className="w-full">
            Authenticate
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}