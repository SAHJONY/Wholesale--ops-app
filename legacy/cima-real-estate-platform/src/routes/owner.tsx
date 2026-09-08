import { createFileRoute } from '@tanstack/react-router'
import { OwnerLogin } from '../components/owner-login'
import { OwnerDashboard } from '../components/owner-dashboard'
import { useState } from 'react'
import { ownerLogin } from '../config/owner-auth'

export const Route = createFileRoute('/owner')({
  component: OwnerRoute,
})

function OwnerRoute() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [ownerData, setOwnerData] = useState(null)

  const handleLoginSuccess = (data: any) => {
    setIsAuthenticated(true)
    setOwnerData(data)
  }

  const handleLogout = () => {
    setIsAuthenticated(false)
    setOwnerData(null)
  }

  if (isAuthenticated && ownerData) {
    return (
      <OwnerDashboard 
        ownerData={ownerData} 
        onLogout={handleLogout} 
      />
    )
  }

  return <OwnerLogin onLoginSuccess={handleLoginSuccess} />
}