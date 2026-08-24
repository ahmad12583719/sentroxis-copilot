import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../App'

describe('Sentroxis Copilot application', () => {
  it('renders the first-run server installation workspace', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /set up your command center/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /wazuh server/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Velociraptor Server' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /connect velociraptor/i })).toBeInTheDocument()
    expect(screen.getByText('Velociraptor wizard')).toBeInTheDocument()
  })

  it('navigates to the branded SOC overview', () => {
    render(<App />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Overview' })[0])
    expect(screen.getByRole('heading', { name: /good morning, analyst/i })).toBeInTheDocument()
    expect(screen.getByText('MITRE ATT&CK matrix')).toBeInTheDocument()
  })
})
