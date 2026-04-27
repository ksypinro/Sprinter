from mcp.server.fastmcp import FastMCP
from OrchestratorMCP.service import OrchestratorMCPService

mcp = FastMCP("SprinterOrchestrator", json_response=True)
service = OrchestratorMCPService()

@mcp.tool()
def getOrchestratorStatus() -> dict:
    return service.get_status()

@mcp.tool()
def listWorkflows() -> list:
    return service.list_workflows()

@mcp.tool()
def getWorkflow(workflowId: str) -> dict:
    return service.get_workflow(workflowId)

@mcp.tool()
def startWorkflow(issueKey: str, issueUrl: str = None) -> dict:
    return service.start_workflow(issueKey, issueUrl)

@mcp.tool()
def retryWorkflow(workflowId: str) -> dict:
    return service.retry_workflow(workflowId)

@mcp.tool()
def pauseWorkflow(workflowId: str) -> dict:
    return service.pause_workflow(workflowId)

@mcp.tool()
def resumeWorkflow(workflowId: str) -> dict:
    return service.resume_workflow(workflowId)

if __name__ == "__main__":
    mcp.run()
