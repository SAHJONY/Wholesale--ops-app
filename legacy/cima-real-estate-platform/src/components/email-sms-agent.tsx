import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export function EmailSMSAgent() {
  const [messageType, setMessageType] = useState<'email' | 'sms'>('email')
  const [recipient, setRecipient] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [result, setResult] = useState('')

  const sendMessage = async () => {
    setIsSending(true)
    setResult('')
    
    try {
      // Simulate sending message
      await new Promise(resolve => setTimeout(resolve, 2000))
      
      setResult(`${messageType.toUpperCase()} sent successfully to ${recipient}`)
    } catch (error) {
      setResult(`Failed to send ${messageType}`)
    }
    
    setIsSending(false)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Email & SMS Agent</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex space-x-4">
            <Button
              variant={messageType === 'email' ? 'default' : 'outline'}
              onClick={() => setMessageType('email')}
            >
              Email
            </Button>
            <Button
              variant={messageType === 'sms' ? 'default' : 'outline'}
              onClick={() => setMessageType('sms')}
            >
              SMS
            </Button>
          </div>
          
          <div>
            <Label htmlFor="recipient">
              {messageType === 'email' ? 'Email Address' : 'Phone Number'}
            </Label>
            <Input
              id="recipient"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              placeholder={messageType === 'email' ? 'email@example.com' : '+1234567890'}
              className="mt-1"
            />
          </div>
          
          {messageType === 'email' && (
            <div>
              <Label htmlFor="subject">Subject</Label>
              <Input
                id="subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Email subject"
                className="mt-1"
              />
            </div>
          )}
          
          <div>
            <Label htmlFor="message">Message</Label>
            <Textarea
              id="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Enter your message here"
              className="mt-1"
              rows={4}
            />
          </div>
          
          <Button 
            onClick={sendMessage} 
            disabled={isSending || !recipient || !message}
            className="w-full"
          >
            {isSending ? 'Sending...' : `Send ${messageType.toUpperCase()}`}
          </Button>
          
          {result && (
            <p className={`text-sm ${result.includes('successfully') ? 'text-green-600' : 'text-red-600'}`}>
              {result}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}