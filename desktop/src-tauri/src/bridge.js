// Runs in every page the window loads; does nothing outside the Dottie server's own origin.
// It stands in for what the web app does not know about: the desktop shell around it.
;(() => {
  if (location.origin !== '__ORIGIN__') return
  const LAST = 'dottie.desktop.last'
  const CHAT = /^\/dotties\/\d+(\/c\/[\w-]+)?\/?$/

  // Reopen where you left off: the first load of "/" in this run goes to the last dottie (and chat) you were in.
  const last = localStorage.getItem(LAST)
  if (location.pathname === '/' && last && !sessionStorage.getItem('dottie.desktop.restored')) {
    sessionStorage.setItem('dottie.desktop.restored', '1')
    location.replace(last)
    return
  }
  const remember = () => {
    if (CHAT.test(location.pathname)) localStorage.setItem(LAST, location.pathname)
  }
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method]
    history[method] = function (...args) {
      const result = original.apply(this, args)
      remember()
      return result
    }
  }
  addEventListener('popstate', remember)
  remember()

  // What the tray shows: whether any dottie is working, and how many messages wait for you.
  const poll = async () => {
    try {
      const res = await fetch('/api/dotties', { credentials: 'same-origin' })
      if (!res.ok) return
      const dotties = await res.json()
      const working = dotties.filter((d) => d.state === 'awake' || d.state === 'queued').map((d) => d.name)
      const unread = dotties.reduce((n, d) => n + d.unread, 0)
      await window.__TAURI_INTERNALS__.invoke('set_status', { working, unread })
    } catch {
      // offline, or not signed in yet: the next poll tries again
    }
  }

  // What dotties write to you: a notification for each new message (the Rust side stays quiet while you look at the
  // window). Not only the unread ones: a hidden window that has the chat open marks it read before you saw it.
  // The first look only learns what is already there.
  let seen = null
  const listen = async () => {
    try {
      const res = await fetch('/api/inbox?limit=10', { credentials: 'same-origin' })
      if (!res.ok) return
      const items = await res.json() // newest first
      const fresh = seen === null ? [] : items.filter((i) => i.message.id > seen).reverse()
      seen = Math.max(seen ?? 0, ...items.map((i) => i.message.id))
      for (const { dottie_id, dottie_name, message } of fresh) {
        const body = message.body.replace(/[*_`#>]/g, '').trim().slice(0, 200)
        await window.__TAURI_INTERNALS__.invoke('notify', {
          title: dottie_name,
          body,
          path: `/dotties/${dottie_id}/c/${message.conversation_id}`,
        })
      }
    } catch {
      // as above
    }
  }
  const tick = () => void Promise.all([poll(), listen()])
  setInterval(tick, 5000)
  tick()
})()
