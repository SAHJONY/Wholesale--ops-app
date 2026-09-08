import { ReactNode } from 'react'

// Basic Card component
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800/50 border border-slate-700 rounded-lg ${className}`}>
      {children}
    </div>
  )
}

export function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`p-6 border-b border-slate-700 ${className}`}>
      {children}
    </div>
  )
}

export function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <h3 className={`text-lg font-semibold text-slate-300 ${className}`}>
      {children}
    </h3>
  )
}

export function CardContent({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`p-6 ${className}`}>
      {children}
    </div>
  )
}

// Basic Button component
export function Button({ 
  children, 
  variant = 'default',
  className = '',
  ...props 
}: { 
  children: ReactNode; 
  variant?: 'default' | 'outline';
  className?: string;
  [key: string]: any;
}) {
  const baseClasses = 'px-4 py-2 rounded-md font-medium transition-colors'
  const variantClasses = {
    default: 'bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white',
    outline: 'border border-slate-600 text-slate-300 hover:bg-slate-700/50'
  }
  
  return (
    <button 
      className={`${baseClasses} ${variantClasses[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

// Basic Badge component
export function Badge({ 
  children, 
  variant = 'default',
  className = '' 
}: { 
  children: ReactNode; 
  variant?: 'default' | 'secondary';
  className?: string;
}) {
  const baseClasses = 'px-2 py-1 text-xs font-medium rounded'
  const variantClasses = {
    default: 'bg-green-500/20 text-green-400',
    secondary: 'bg-red-500/20 text-red-400'
  }
  
  return (
    <span className={`${baseClasses} ${variantClasses[variant]} ${className}`}>
      {children}
    </span>
  )
}

// Basic Tabs components
export function Tabs({ 
  value, 
  onValueChange, 
  children, 
  className = '' 
}: { 
  value: string; 
  onValueChange: (value: string) => void; 
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      {children}
    </div>
  )
}

export function TabsList({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`grid w-full grid-cols-5 bg-slate-800/50 p-1 rounded-lg ${className}`}>
      {children}
    </div>
  )
}

export function TabsTrigger({ 
  value, 
  children, 
  className = '' 
}: { 
  value: string; 
  children: ReactNode;
  className?: string;
}) {
  return (
    <button 
      className={`data-[state=active]:bg-slate-700 text-slate-300 px-4 py-2 rounded-md transition-colors ${className}`}
      data-state={value}
    >
      {children}
    </button>
  )
}

export function TabsContent({ 
  value, 
  children, 
  className = '' 
}: { 
  value: string; 
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      {children}
    </div>
  )
}