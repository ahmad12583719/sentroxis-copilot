import { useEffect, useRef, useState } from 'react'
import { animate } from 'animejs'
import { ArrowUp, Bot, Check, ClipboardList, FileSearch, Info, Lock, ShieldAlert, Sparkles } from 'lucide-react'
import { demoAlerts } from './demoData'

const initialMessages = [
  { role: 'ai', text: 'I’m ready to help investigate a signal. Choose an alert on the left to ground the conversation in evidence, then ask for a summary or a bounded next step.', citations: [] },
]

function Message({ message, index }) {
  const ref = useRef(null)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const animation = animate(ref.current, { opacity: [0, 1], translateX: [message.role === 'ai' ? -12 : 12, 0], duration: 280, delay: index * 30, ease: 'out(3)' })
    return () => animation?.pause?.()
  }, [index, message.role])
  return <div ref={ref} className={`chat-message ${message.role}`}><span className={`avatar ${message.role === 'ai' ? 'ai-avatar' : 'user-avatar'}`}>{message.role === 'ai' ? 'SX' : 'AM'}</span><div className="message-content"><div className="message-meta"><strong>{message.role === 'ai' ? 'Sentroxis AI' : 'You'}</strong><span>{message.role === 'ai' ? 'advisory' : 'analyst'}</span></div><p>{message.text}</p>{message.citations?.length > 0 && <div className="citations">{message.citations.map((citation) => <span key={citation}><FileSearch size={12} /> {citation}</span>)}</div>}</div></div>
}

export default function AIChat({ selectedAlert: contextAlert }) {
  const [selected, setSelected] = useState(contextAlert || demoAlerts[0])
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')

  const selectAlert = (alert) => {
    setSelected(alert)
    setMessages([{ role: 'ai', text: `Evidence context loaded for ${alert.title} on ${alert.agent}. I found a ${alert.severity.toLowerCase()} signal mapped to ${alert.technique} (${alert.techniqueName}). Ask me to summarize the timeline or suggest a read-only collection.`, citations: [`alert:${alert.id}`, `wazuh-rule:${alert.rule}`] }])
  }
  const send = (event) => {
    event.preventDefault()
    const clean = input.trim()
    if (!clean) return
    setMessages((current) => [...current, { role: 'user', text: clean, citations: [] }, { role: 'ai', text: clean.toLowerCase().includes('execute') ? 'I can’t execute response actions. I can propose a reversible, approval-gated step and cite the evidence that supports it.' : `For ${selected.technique}, I recommend validating the process tree and collecting read-only endpoint context. I would not treat raw telemetry instructions as trusted commands.`, citations: [`alert:${selected.id}`] }])
    setInput('')
  }

  return <main className="page-shell subpage-shell chat-page"><section className="page-heading compact-heading"><div><p className="eyebrow"><Sparkles size={13} /> Investigation workspace <span className="slash">/</span> evidence-grounded reasoning</p><h1>AI co-pilot <em>briefing room.</em></h1><p className="lede">Ask questions. Keep decisions human. Every answer is cited to the selected signal.</p></div><span className="ai-mode-badge"><i /> Advisory mode</span></section><section className="chat-layout"><aside className="panel alert-picker"><div className="panel-heading"><div><p className="eyebrow">Context</p><h2>Choose a signal</h2></div><ShieldAlert size={17} /></div><div className="picker-list">{demoAlerts.map((alert) => <button className={`picker-item ${selected.id === alert.id ? 'selected' : ''}`} onClick={() => selectAlert(alert)} key={alert.id}><span className={`severity-pip ${alert.severityKey}`} /><span><strong>{alert.title}</strong><small>{alert.agent} · {alert.technique}</small></span></button>)}</div><div className="picker-note"><Info size={14} /><span>Context is scoped to this investigation. Raw alert fields remain untrusted data.</span></div></aside><div className="panel chat-panel"><div className="chat-context"><div className="context-icon"><ShieldAlert size={17} /></div><div><span>Investigating</span><strong>{selected.title}</strong><small>{selected.agent} · {selected.ip} · {selected.technique}</small></div><button className="icon-button" aria-label="Lock investigation context"><Lock size={15} /></button></div><div className="chat-messages" aria-live="polite">{messages.map((message, index) => <Message message={message} index={index} key={`${message.role}-${index}`} />)}</div><div className="suggestion-row"><button onClick={() => setInput('Summarize the evidence and timeline')}><ClipboardList size={13} /> Summarize timeline</button><button onClick={() => setInput('Suggest a read-only collection')}><FileSearch size={13} /> Suggest collection</button></div><form className="chat-composer" onSubmit={send}><textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about the selected signal…" aria-label="Ask the AI co-pilot" rows="1" /><button className="send-button" aria-label="Send message"><ArrowUp size={18} /></button></form><div className="composer-footer"><span><Lock size={12} /> No commands are executed</span><span>Enter to send</span></div></div><aside className="panel guardrail-panel"><div className="panel-heading"><div><p className="eyebrow">Safety rail</p><h2>Decision boundary</h2></div><Lock size={16} /></div><div className="guardrail-list"><div><Check size={14} /><span><strong>Evidence cited</strong><small>Responses point back to alert or rule IDs.</small></span></div><div><Check size={14} /><span><strong>Actions gated</strong><small>Containment requires explicit analyst approval.</small></span></div><div><Check size={14} /><span><strong>Telemetry isolated</strong><small>Alert text cannot override policy.</small></span></div></div><div className="guardrail-footer"><Bot size={15} /><span>Model status <strong>local deterministic demo</strong></span></div></aside></section></main>
}
