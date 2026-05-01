import argparse
import json
import sys
from orchestrator.settings import OrchestratorSettings
from orchestrator.service import OrchestratorService

def main():
    parser = argparse.ArgumentParser(description="Control Sprinter workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Start
    start_p = subparsers.add_parser("start", help="Submit a jira.issue.created event")
    start_p.add_argument("--key", required=True, help="Jira issue key")
    start_p.add_argument("--url", help="Jira issue URL")

    # Pause
    pause_p = subparsers.add_parser("pause", help="Pause a workflow")
    pause_p.add_argument("--key", required=True, help="Workflow ID")

    # Resume
    resume_p = subparsers.add_parser("resume", help="Resume a paused workflow")
    resume_p.add_argument("--key", required=True, help="Workflow ID")

    # Retry
    retry_p = subparsers.add_parser("retry", help="Retry a blocked workflow")
    retry_p.add_argument("--key", required=True, help="Workflow ID")

    parser.add_argument("--config", default="orchestrator/config.yaml", help="Path to orchestrator config.yaml")

    args = parser.parse_args()

    try:
        settings = OrchestratorSettings.from_env()
        service = OrchestratorService(settings)
        service.initialize(start_webhooks=False)

        if args.command == "start":
            event_id = service.submit_jira_created(args.key, args.url)
            print(json.dumps({"status": "submitted", "event_id": event_id, "workflow_id": args.key}, indent=2))
        elif args.command == "pause":
            service.pause_workflow(args.key)
            print(json.dumps({"status": "pause_requested", "workflow_id": args.key}, indent=2))
        elif args.command == "resume":
            service.resume_workflow(args.key)
            print(json.dumps({"status": "resume_requested", "workflow_id": args.key}, indent=2))
        elif args.command == "retry":
            service.retry_workflow(args.key)
            print(json.dumps({"status": "retry_requested", "workflow_id": args.key}, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
