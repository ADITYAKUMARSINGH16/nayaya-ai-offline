/**
 * Tiny SSE-over-POST client.
 *
 * Why not the browser's EventSource? EventSource is GET-only and can't send
 * an Authorization header. Our /api/*​/stream endpoints are POST + JSON body,
 * so we fetch with `stream: true` and parse the `data:` lines manually.
 *
 * Usage:
 *   await streamPost('/api/assistant/stream', payload, {
 *     headers: { Authorization: `Bearer ${jwt}` },
 *     onEvent: (name, data) => { ... },
 *     signal,
 *   })
 */
export async function streamPost(
  url,
  body,
  { headers = {}, onEvent, signal } = {},
) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = ''
    try { detail = (await res.json())?.detail || '' } catch { /* noop */ }
    throw new Error(`${res.status} ${detail || res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = 'message'

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE messages are separated by blank lines
    const parts = buffer.split(/\r?\n\r?\n/)
    buffer = parts.pop() ?? ''

    for (const block of parts) {
      let data = ''
      event = 'message'
      for (const line of block.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue
        if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          // SSE spec: "data: <value>" — strip ONLY the single space after the
          // colon, never .trim(). Trimming destroys leading-space tokens like
          // " Sections" that LLMs emit, causing words to run together.
          let value = line.slice(5)
          if (value.startsWith(' ')) value = value.slice(1)
          data += (data ? '\n' : '') + value
        }
      }
      if (event || data) onEvent?.(event, data)
    }
  }
}
