import { createServer, type ServerResponse } from 'node:http'

import type { ScoutSession } from '../../src/lib/contracts'

export async function startSessionEvents(read: (id: string) => ScoutSession | undefined) {
  const listeners = new Map<string, Set<ServerResponse>>()
  const connections: string[] = []
  function send(response: ServerResponse, snapshot: ScoutSession) {
    if (response.writableEnded || response.destroyed) return
    response.write(`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`)
    if (snapshot.outcome !== 'running' && snapshot.outcome !== 'queued') response.end()
  }
  const server = createServer((request, response) => {
    const id = decodeURIComponent(request.url!.split('/')[4]!)
    const snapshot = read(id)
    if (!snapshot) {
      response.writeHead(404, { 'Access-Control-Allow-Origin': '*' })
      response.end()
      return
    }
    connections.push(id)
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Access-Control-Allow-Origin': '*',
    })
    response.write('retry: 100\n\n')
    const subscribers = listeners.get(id) || new Set<ServerResponse>()
    listeners.set(id, subscribers)
    subscribers.add(response)
    response.on('close', () => subscribers.delete(response))
    send(response, snapshot)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Missing event server address')
  return {
    origin: `http://127.0.0.1:${address.port}`,
    connections,
    active: () => [...listeners.values()].reduce((total, current) => total + current.size, 0),
    publish: (snapshot: ScoutSession) => {
      for (const response of listeners.get(snapshot.session_id) || []) send(response, snapshot)
    },
    disconnect: (id: string) => {
      for (const response of listeners.get(id) || []) response.end()
    },
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections()
        server.close((error) => (error ? reject(error) : resolve()))
      }),
  }
}
