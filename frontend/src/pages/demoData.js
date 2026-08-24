export const demoAlerts = [
  { id: 'wazuh-demo-001', title: 'PowerShell encoded command execution', source: 'Wazuh', severity: 'Critical', severityKey: 'critical', agent: 'ws-fin-07', ip: '10.20.4.17', time: '08:21:04', tactic: 'Execution', technique: 'T1059.001', techniqueName: 'PowerShell', rule: '100001' },
  { id: 'wazuh-demo-002', title: 'New scheduled task created', source: 'Wazuh', severity: 'High', severityKey: 'high', agent: 'srv-app-02', ip: '10.20.8.42', time: '08:14:36', tactic: 'Persistence', technique: 'T1053.005', techniqueName: 'Scheduled Task', rule: '100002' },
  { id: 'wazuh-demo-003', title: 'Suspicious LSASS access', source: 'Wazuh', severity: 'High', severityKey: 'high', agent: 'dc-east-01', ip: '10.20.1.11', time: '07:58:11', tactic: 'Credential Access', technique: 'T1003', techniqueName: 'OS Credential Dumping', rule: '100003' },
  { id: 'vr-demo-014', title: 'Unexpected service binary modified', source: 'Velociraptor', severity: 'Medium', severityKey: 'medium', agent: 'ws-ops-12', ip: '10.20.6.9', time: '07:40:52', tactic: 'Defense Evasion', technique: 'T1562.001', techniqueName: 'Impair Defenses', rule: 'artifact:Windows.System.Services' },
]
