import argparse
import json
import sys
import os
from JiraStreamableMCP.service import JiraStreamableService

def main():
    parser = argparse.ArgumentParser(description="Export a Jira issue and linked Confluence pages.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Full Jira issue URL")
    group.add_argument("--key", help="Jira issue key (requires jira.base_url in config)")
    parser.add_argument("--config", default="config.yaml", help="Path to Sprinter config.yaml")

    args = parser.parse_args()

    try:
        service = JiraStreamableService(config_path=args.config)
        
        ticket_url = args.url
        if not ticket_url:
            # Construct URL from key if not provided, assuming config has it or let service handle error
            from main import load_config
            cfg = load_config(args.config)
            base_url = cfg.get("jira", {}).get("base_url", "").rstrip("/")
            if not base_url:
                print(json.dumps({"error": "No jira.base_url found in config to resolve key to URL."}, indent=2), file=sys.stderr)
                sys.exit(1)
            ticket_url = f"{base_url}/browse/{args.key}"

        result = service.export_issue(ticket_url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
