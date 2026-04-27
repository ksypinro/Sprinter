from typing import Optional
from orchestrator.models import OrchestratorEvent
from orchestrator.service import OrchestratorService
from orchestrator.settings import OrchestratorSettings

class OrchestratorMCPService:
    def __init__(self):
        self.settings = OrchestratorSettings.from_env()
        self.service = OrchestratorService(self.settings)

    def get_status(self):
        self.service.initialize()
        workflows = self.service.store.list_workflows()
        return {
            "storage_root": str(self.settings.storage_root),
            "workflows_count": len(workflows),
            "workflows": [w.to_dict() for w in workflows]
        }

    def list_workflows(self):
        self.service.initialize()
        return [w.to_dict() for w in self.service.store.list_workflows()]

    def get_workflow(self, workflow_id: str):
        state = self.service.get_workflow_state(workflow_id)
        return state.to_dict() if state else None

    def start_workflow(self, issue_key: str, issue_url: Optional[str] = None):
        event_id = self.service.submit_jira_created(issue_key, issue_url)
        return {"status": "accepted", "event_id": event_id}

    def retry_workflow(self, workflow_id: str):
        self.service.retry_workflow(workflow_id)
        return {"status": "accepted"}

    def pause_workflow(self, workflow_id: str):
        self.service.pause_workflow(workflow_id)
        return {"status": "accepted"}

    def resume_workflow(self, workflow_id: str):
        self.service.resume_workflow(workflow_id)
        return {"status": "accepted"}
