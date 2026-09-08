import { type ComponentPropsWithoutRef, forwardRef } from 'react'
import { clsx } from 'clsx'

const Progress = forwardRef<HTMLDivElement, ComponentPropsWithoutRef<'div'> & {
  value?: number
}>(
  ({ className, value = 0, ...props }, ref) => {
    const percentage = Math.max(0, Math.min(100, value))
    
    return (
      <div
        ref={ref}
        className={clsx(
          'relative h-2 w-full overflow-hidden rounded-full bg-secondary',
          className
        )}
        {...props}
      >
        <div
          className="h-full w-full flex-1 bg-primary transition-all"
          style={{
            transform: `translateX(-${100 - percentage}%)`,
          }}
        />
      </div>
    )
  }
)
Progress.displayName = 'Progress'

export { Progress }