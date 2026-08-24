import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const setupState = (endpoint = null) => ({ servers: [{ key: 'wazuh', name: 'Wazuh Server', tagline: 'Detection and alert telemetry', description: 'Wazuh', status: endpoint ? 'ready' : 'not_started', endpoint, version: null, steps: [{ id: 'wazuh-endpoint', title: 'Manager endpoint', description: 'Endpoint' }] }, { key: 'velociraptor', name: 'Velociraptor Server', tagline: 'Endpoint evidence collection', description: 'Velociraptor', status: endpoint ? 'ready' : 'not_started', endpoint, version: null, steps: [{ id: 'vr-endpoint', title: 'Server endpoint', description: 'Endpoint' }] }] })

function response(data, ok = true) { return Promise.resolve({ ok, json: () => Promise.resolve(data) }) }

describe('Sentroxis Copilot application', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    global.fetch = vi.fn((url) => {
      if (url === '/api/auth/status') return response({ authenticated: false, registration_open: true, user: null })
      return response({})
    })
  })

  it('requires authentication and offers first-account registration', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { name: /create the first account/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create secure account/i })).toBeInTheDocument()
  })

  it('opens the first-run installation setup after authentication', async () => {
    global.fetch = vi.fn((url) => {
      if (url === '/api/auth/status') return response({ authenticated: true, registration_open: false, user: { id: 'usr-1', name: 'Test Analyst', email: 'test@example.com', role: 'admin' } })
      if (url === '/api/setup') return response(setupState())
      if (url.startsWith('/api/alerts')) return response({ items: [], total: 0 })
      return response({})
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: /set up your command center/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /wazuh server/i })).toBeInTheDocument()
    expect(screen.getAllByText(/open installation/i)).toHaveLength(2)
    expect(screen.queryByText(/powerShell encoded/i)).not.toBeInTheDocument()
  })

  it('opens integration setup when a server is already configured', async () => {
    global.fetch = vi.fn((url) => {
      if (url === '/api/auth/status') return response({ authenticated: true, registration_open: false, user: { id: 'usr-1', name: 'Test Analyst', email: 'test@example.com', role: 'admin' } })
      if (url === '/api/setup') return response(setupState('https://wazuh.internal'))
      return response({ items: [], total: 0 })
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: /configure your data plane/i })).toBeInTheDocument()
    expect(screen.getByText(/existing security servers detected/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/update connection/i)).toBeInTheDocument())
  })
})
