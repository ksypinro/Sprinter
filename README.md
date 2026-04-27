# Sprinter
 
 A toolkit for local Jira/Confluence extraction, Codex analysis, and automated orchestration.
 
-## V2: Orchestration Engine
-
-Sprinter now includes a durable orchestration engine that handles multi-step workflows (Export -> Analyze -> Execute -> Review).
-
-### Architecture
-
-![Architecture](architecture.html)
-
-### Quick Start
-
-1. **Observe Jira**: Start the webhook listener and register it with Jira.
-   ```bash
-   .venv/bin/python webhooks/server.py
-   .venv/bin/python webhooks/setup.py
-   ```
-
-2. **Start Orchestrator**: Run the event loop to process incoming triggers.
-   ```bash
-   .venv/bin/python -m orchestrator start
-   ```
-
-3. **Inspect Workflows**: Use the CLI or MCP to monitor progress.
-   ```bash
-   .venv/bin/python -m orchestrator status
-   ```
-
 ## Installation
 
 1.  **Clone the repository**:
@@ -75,6 +49,30 @@
     -   `JiraWebhookMCP`: Standard Webhook integration for Jira.
     -   `JiraSSEMCP`: Jira event stream via Server-Sent Events.
     -   `JiraStreamableMCP`: Streamable HTTP server for issue export.
+    -   `OrchestratorMCP`: Controls and observes the Sprinter orchestration engine.
+
+## V2: Orchestration Engine
+
+Sprinter now includes a durable orchestration engine that handles multi-step workflows (Export -> Analyze -> Execute -> Review).
+
+### Architecture
+
+For a detailed visual overview, see the [Architectural Documentation](architecture.html).
+
+### Quick Start
+
+1. **Observe Jira**: Start the webhook listener and register it with Jira.
+   ```bash
+   .venv/bin/python webhooks/server.py
+   .venv/bin/python webhooks/setup.py
+   ```
+
+2. **Start Orchestrator**: Run the event loop to process incoming triggers.
+   ```bash
+   .venv/bin/python -m orchestrator start
+   ```
+
+3. **Inspect Workflows**: Use the CLI or MCP to monitor progress.
+   ```bash
+   .venv/bin/python -m orchestrator status
+   ```
 
 ## License
 
