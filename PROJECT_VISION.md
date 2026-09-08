Sentroxis Copilot: Comprehensive Project Vision & Functional Blueprint
1. Executive Summary & Project Definition
Sentroxis is an advanced, AI-assisted Security Operations Center (SOC) copilot and academic command center designed to automate the ingestion, analysis, and visualization of security telemetry. It serves as an integrated wrapper and analytical layer over enterprise-grade security tools, specifically Wazuh and Velociraptor, combining real-time SIEM monitoring with automated incident response capabilities and an intuitive React frontend.

2. Core Purpose & What Sentroxis Does
Sentroxis bridges the gap between raw security log generation and actionable intelligence. Specifically, it performs the following core functions:

Agentic SOC Automation: Automates the ingestion and analysis of telemetry from Wazuh managers, indexers, and Velociraptor endpoints.

Unified Dashboard Interface: Embeds and routes security data (such as the Wazuh Dashboard) directly through a same-origin Nginx proxy (/wazuh/), eliminating browser iframe blocking and cross-origin security friction.

Local Academic Command Center: Manages academic coursework, timetables, assignments, and local encrypted data backups alongside security operations.

Zero-Touch Deployment (FR-32): Strictly enforces a "clone, build, and run" philosophy where executing a single command (./startup.sh) automatically provisions build contexts, configures environment variables, builds custom Docker images, passes authenticated OpenSearch health checks, and starts the entire multi-container stack.

3. Deep Dive into the Wazuh Integration
Wazuh is the core SIEM and Extended Detection and Response (XDR) backbone of Sentroxis.

Architecture: It runs as a multi-container single-node deployment managed via Docker Compose (docker-compose.yml combined with the Sentroxis override docker-compose.sentroxis.yml).

Components Utilized:

wazuh.indexer (OpenSearch-based data engine for storing security events and alerts, requiring vm.max_map_count set to 262144 on the Ubuntu host).

wazuh.manager (The core detection engine processing agent logs, alerts, and custom Filebeat integrations via a custom-built image: sentroxis/wazuh-manager:4.7.5-archives).

wazuh.dashboard & wazuh.dashboard_proxy (The visualization layer exposed securely via Nginx reverse proxy routing on port 443).

Operational Role: Sentroxis interacts with Wazuh's manager API (port 55000) and indexer (port 9200) to pull telemetry, monitor host integrity, and present security insights directly to the user within a unified dashboard interface.

4. Technical Stack & Environment
Backend: Python, FastAPI, Uvicorn, Pydantic, SQLite (for user identity and local application state management).

Frontend: React.js, Vite, Tailwind CSS.

Endpoint & Forensics: Project-local Velociraptor server for deep endpoint visibility and artifact collection.

Host Environment: Ubuntu Linux, utilizing Ubuntu Sentinel and automated host log monitoring scripts.

5. Non-Negotiable Engineering Constraints
Strict Automation (FR-32): No manual terminal edits, manual Docker Compose flag tweaking, or manual health-check fixes are allowed. Scripts must handle everything self-sufficiently.

Robust Health Gates (NFR-22): Startup routines must probe OpenSearch using authenticated HTTPS requests (/_cluster/health) with proper TLS handling and bounded retries to prevent false-positive failures.
