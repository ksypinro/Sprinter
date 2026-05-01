import argparse
import json
import sys
import os
from pathlib import Path
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import OrchestratorStore

def main():
    parser = argparse.ArgumentParser(description="Query orchestrator workflow status.")
    parser.add_argument("--key", help="Jira issue key / workflow ID")
    parser.add_argument("--history", action="store_true", help="Include event history (only with --key)")
    parser.add_argument("--config", default="orchestrator/config.yaml", help="Path to orchestrator config.yaml")

    args = parser.parse_args()

    try:
        # Resolve config path relative to repo root if needed, but normally run from repo root
        settings = OrchestratorSettings.from_env()
        store = OrchestratorStore(settings.storage_root)

        if args.key:
            state = store.read_workflow_state(args.key)
            if not state:
                print(json.dumps({"error": f"Workflow {args.key} not found."}, indent=2), file=sys.stderr)
                sys.exit(1)
            
            output = state.to_dict()
            if not args.history:
                output.pop("history", None)
            print(json.dumps(output, indent=2))
        else:
            workflows = store.list_workflows()
            print(json.dumps([w.to_dict() for w in workflows], indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
