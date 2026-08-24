import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../App'

describe('Sentroxis Copilot application', () => {
  it('renders the branded SOC overview', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /go to sentroxis overview/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /good morning, analyst/i })).toBeInTheDocument()
    expect(screen.getByText('MITRE ATT&CK matrix')).toBeInTheDocument()
    expect(screen.getByText('Wazuh indexer · connected')).toBeInTheDocument()
  })

  it('exposes accessible navigation controls', () => {
    render(<App />)
    expect(screen.getByRole('navigation', { name: /primary navigation/i })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /workspace navigation/i })).toBeInTheDocument()
  })
})
