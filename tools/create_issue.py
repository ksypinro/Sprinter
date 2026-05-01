import argparse
import json
import sys
from JiraStreamableMCP.service import JiraStreamableService

def main():
    parser = argparse.ArgumentParser(description="Create a Jira issue.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--payload", help="JSON payload string")
    group.add_argument("--file", help="Path to JSON file containing payload")
    parser.add_argument("--config", default="config.yaml", help="Path to Sprinter config.yaml")

    args = parser.parse_args()

    try:
        if args.payload:
            payload = json.loads(args.payload)
        else:
            with open(args.file, "r") as f:
                payload = json.load(f)

        service = JiraStreamableService(config_path=args.config)
        result = service.create_issue(payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
