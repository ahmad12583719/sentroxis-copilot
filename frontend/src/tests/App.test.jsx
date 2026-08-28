import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

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

  it('opens the Wazuh workspace with exactly four primary tabs after authentication', async () => {
    global.fetch = vi.fn((url) => {
      if (url === '/api/auth/status') return response({ authenticated: true, registration_open: false, user: { id: 'usr-1', name: 'Test Analyst', email: 'test@example.com', role: 'admin' } })
      if (url.startsWith('/api/alerts')) return response({ items: [], total: 0 })
      return response({})
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: /your security command center/i })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Wazuh' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Velociraptor' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Endpoints' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'AI co-pilot' }).length).toBeGreaterThan(0)
    expect(screen.getByTitle('Wazuh dashboard')).toBeInTheDocument()
  })

  it('opens the Wazuh agent management tab from the primary navigation', async () => {
    global.fetch = vi.fn((url) => {
      if (url === '/api/auth/status') return response({ authenticated: true, registration_open: false, user: { id: 'usr-1', name: 'Test Analyst', email: 'test@example.com', role: 'admin' } })
      if (url.startsWith('/api/alerts')) return response({ items: [], total: 0 })
      return response({})
    })
    render(<App />)
    await screen.findByRole('heading', { name: /your security command center/i })
    fireEvent.click(screen.getAllByRole('button', { name: 'Endpoints' })[0])
    expect(await screen.findByRole('heading', { name: /prepare your endpoints/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /velociraptor package prerequisites/i })).toBeInTheDocument()
  })
})
