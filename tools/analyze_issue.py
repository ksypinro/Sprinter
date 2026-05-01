import argparse
import json
import sys
from pathlib import Path
from codex_analysis.service import create_codex_analysis_service
from webhooks.models import WebhookEvent

def main():
    parser = argparse.ArgumentParser(description="Run Codex analysis on an exported Jira issue.")
    parser.add_argument("--key", required=True, help="Jira issue key")
    parser.add_argument("--issue-dir", help="Directory containing exported issue artifacts")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")

    args = parser.parse_args()

    try:
        repo_root = Path(args.repo_root).resolve()
        analysis_service = create_codex_analysis_service(repo_root=repo_root)
        
        if not analysis_service:
            print(json.dumps({"error": "Codex analysis service could not be initialized (check config/env)."}, indent=2), file=sys.stderr)
            sys.exit(1)

        issue_dir = args.issue_dir or str(repo_root / "exports" / args.key)
        manifest_path = str(Path(issue_dir) / "export_manifest.json")

        # Create a dummy event for the service
        event = WebhookEvent(
            provider="tools",
            event_id="tool-analyze",
            event_type="tool:analyze_issue",
            issue_key=args.key,
            issue_url=args.key,
            actor="user",
            raw_payload={}
        )

        result = analysis_service.analyze_export(event, {
            "issue_key": args.key,
            "issue_dir": issue_dir,
            "manifest_path": manifest_path,
        })
        
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
