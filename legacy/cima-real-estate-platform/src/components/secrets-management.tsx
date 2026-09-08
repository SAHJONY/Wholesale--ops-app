import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function SecretsManagement() {
  const [secrets, setSecrets] = useState<Array<{key: string, value: string}>>([])
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  const addSecret = () => {
    if (newKey && newValue) {
      setSecrets([...secrets, { key: newKey, value: newValue }])
      setNewKey('')
      setNewValue('')
    }
  }

  const removeSecret = (index: number) => {
    setSecrets(secrets.filter((_, i) => i !== index))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Secrets Management</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="secret-key">Key</Label>
              <Input
                id="secret-key"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="API_KEY"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="secret-value">Value</Label>
              <Input
                id="secret-value"
                type="password"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                placeholder="Your secret value"
                className="mt-1"
              />
            </div>
          </div>
          
          <Button onClick={addSecret} disabled={!newKey || !newValue} className="w-full">
            Add Secret
          </Button>
          
          {secrets.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium">Current Secrets:</p>
              {secrets.map((secret, index) => (
                <div key={index} className="flex items-center justify-between p-2 bg-gray-100 rounded">
                  <span className="text-sm font-mono">{secret.key}</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => removeSecret(index)}
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}