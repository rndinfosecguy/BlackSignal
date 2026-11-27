/**
 * Reference-counted body scroll lock.
 *
 * Locks both <html> and <body> (the horizontal scrollbar otherwise leaves a
 * strip at the bottom of fixed overlays) and compensates for the vertical
 * scrollbar so the page doesn't shift sideways while a modal is open.
 */

let locks = 0
let previousBodyOverflow = ''
let previousHtmlOverflow = ''
let previousPaddingRight = ''

export function lockScroll(): () => void {
  if (locks === 0) {
    const root = document.documentElement
    const scrollbar = window.innerWidth - root.clientWidth

    previousBodyOverflow = document.body.style.overflow
    previousHtmlOverflow = root.style.overflow
    previousPaddingRight = document.body.style.paddingRight

    root.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    if (scrollbar > 0) {
      document.body.style.paddingRight = `${scrollbar}px`
    }
  }
  locks += 1

  let released = false
  return () => {
    if (released) return
    released = true
    locks = Math.max(0, locks - 1)
    if (locks === 0) {
      document.documentElement.style.overflow = previousHtmlOverflow
      document.body.style.overflow = previousBodyOverflow
      document.body.style.paddingRight = previousPaddingRight
    }
  }
}