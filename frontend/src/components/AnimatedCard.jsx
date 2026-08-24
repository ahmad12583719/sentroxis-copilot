import { useEffect, useRef } from 'react'
import { animate } from 'animejs'

export default function AnimatedCard({ children, className = '', index = 0 }) {
  const cardRef = useRef(null)

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const animation = animate(cardRef.current, {
      opacity: [0, 1],
      translateY: [16, 0],
      duration: 460,
      delay: index * 65,
      ease: 'out(3)',
    })
    return () => animation?.pause?.()
  }, [index])

  return <article ref={cardRef} className={`metric-card ${className}`}>{children}</article>
}
