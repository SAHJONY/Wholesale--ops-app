import { createFileRoute } from '@tanstack/react-router'
import { usePageTitle } from '@/hooks/use-page-title'
import { RealEstateDashboard } from '@/screens/real-estate/real-estate-dashboard'

export const Route = createFileRoute('/real-estate')({
  component: RealEstateRoute,
})

function RealEstateRoute() {
  usePageTitle('Real Estate Dashboard')
  return <RealEstateDashboard />
}