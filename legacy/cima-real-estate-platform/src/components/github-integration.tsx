import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function GitHubIntegration() {
  const [repoUrl, setRepoUrl] = useState('')
  const [githubToken, setGithubToken] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState('')

  const cloneRepository = async () => {
    setIsLoading(true)
    setResult('')
    
    try {
      // Simulate GitHub API integration
      const response = await fetch('/api/github/clone', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${githubToken}`
        },
        body: JSON.stringify({ repoUrl })
      })
      
      if (response.ok) {
        setResult('Repository cloned successfully!')
      } else {
        setResult('Failed to clone repository')
      }
    } catch (error) {
      setResult('Error cloning repository')
    }
    
    setIsLoading(false)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>GitHub Repository Integration</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <Label htmlFor="repo-url">Repository URL</Label>
            <Input
              id="repo-url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/user/repo.git"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="github-token">GitHub Token</Label>
            <Input
              id="github-token"
              type="password"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              placeholder="Enter GitHub token"
              className="mt-1"
            />
          </div>
          <Button 
            onClick={cloneRepository} 
            disabled={isLoading || !repoUrl || !githubToken}
            className="w-full"
          >
            {isLoading ? 'Cloning...' : 'Clone Repository'}
          </Button>
          {result && (
            <p className="text-sm text-green-600">{result}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}