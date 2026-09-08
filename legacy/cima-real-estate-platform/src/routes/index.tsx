import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  ssr: false,
  beforeLoad: function redirectToRealEstate() {
    throw redirect({
      to: '/real-estate' as string,
      replace: true,
    })
  },
  component: function IndexRoute() {
    return null
  },
})
