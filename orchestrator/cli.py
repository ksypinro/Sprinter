import logging
import signal
import sys
import time
from typing import Optional

from orchestrator.service import OrchestratorService
from orchestrator.settings import OrchestratorSettings

logger = logging.getLogger("orchestrator.cli")

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="orchestrator")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("start", help="Start the orchestrator event loop and dispatcher.")
    
    status_parser = subparsers.add_parser("status", help="Show orchestrator status.")
    status_parser.add_argument("--json", action="store_true", help="Output JSON.")

    workflow_parser = subparsers.add_parser("workflow", help="Show workflow state.")
    workflow_parser.add_argument("workflow_id", help="Issue key (e.g. SCRUM-13)")
    workflow_parser.add_argument("--history", action="store_true", help="Show event history.")

    submit_jira_parser = subparsers.add_parser("submit-jira-created", help="Manually submit jira.issue.created event.")
    submit_jira_parser.add_argument("workflow_id", help="Issue key.")
    submit_jira_parser.add_argument("--url", help="Jira issue URL.")

    retry_parser = subparsers.add_parser("retry", help="Manually retry a workflow.")
    retry_parser.add_argument("workflow_id", help="Issue key.")

    pause_parser = subparsers.add_parser("pause", help="Pause a workflow.")
    pause_parser.add_argument("workflow_id", help="Issue key.")

    resume_parser = subparsers.add_parser("resume", help="Resume a workflow.")
    resume_parser.add_argument("workflow_id", help="Issue key.")

    args = parser.parse_args(argv or sys.argv[1:])

    settings = OrchestratorSettings.from_env()
    service = OrchestratorService(settings)

    if args.command == "start":
        return run_loop(service)
    elif args.command == "status":
        service.initialize()
        workflows = service.store.list_workflows()
        if args.json:
            import json
            print(json.dumps([w.to_dict() for w in workflows], indent=2))
        else:
            print(f"Orchestrator Status ({settings.storage_root})")
            print(f"Workflows: {len(workflows)}")
            for w in workflows:
                print(f"  {w.workflow_id}: {w.status} (active_command: {w.active_command_id or 'none'})")
        return 0
    elif args.command == "workflow":
        state = service.get_workflow_state(args.workflow_id)
        if not state:
            print(f"Workflow not found: {args.workflow_id}")
            return 1
        import json
        print(json.dumps(state.to_dict(), indent=2))
        if args.history:
            history = service.store.read_workflow_history(args.workflow_id)
            print("\nHistory:")
            for event in history:
                print(f"  {event.get('received_at')} - {event.get('event_type')}")
        return 0
    elif args.command == "submit-jira-created":
        event_id = service.submit_jira_created(args.workflow_id, args.url)
        print(f"Submitted event: {event_id}")
        return 0
    elif args.command == "retry":
        service.retry_workflow(args.workflow_id)
        print(f"Retry requested for: {args.workflow_id}")
        return 0
    elif args.command == "pause":
        service.pause_workflow(args.workflow_id)
        print(f"Paused: {args.workflow_id}")
        return 0
    elif args.command == "resume":
        service.resume_workflow(args.workflow_id)
        print(f"Resumed: {args.workflow_id}")
        return 0

    parser.print_help()
    return 1

def run_loop(service: OrchestratorService) -> int:
    service.initialize()
    logger.info("Starting orchestrator event loop and dispatcher")

    def handle_sigterm(*_):
        logger.info("Shutdown requested")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        while True:
            processed = service.process_pending_events(limit=10)
            dispatched = service.dispatcher.dispatch_all_workers()
            if not processed and not dispatched:
                time.sleep(service.settings.event_poll_interval_seconds)
    except Exception:
        logger.exception("Orchestrator loop crashed")
        return 1
    return 0
