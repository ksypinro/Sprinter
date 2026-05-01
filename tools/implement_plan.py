import argparse
import json
import sys
from pathlib import Path
from codex_implementer.service import create_codex_implementer_service

def main():
    parser = argparse.ArgumentParser(description="Execute a Codex implementation plan.")
    parser.add_argument("--key", required=True, help="Jira issue key")
    parser.add_argument("--analysis-path", help="Path to the analysis_and_plan.md file")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")

    args = parser.parse_args()

    try:
        repo_root = Path(args.repo_root).resolve()
        implementer_service = create_codex_implementer_service(repo_root=repo_root)
        
        if not implementer_service:
            print(json.dumps({"error": "Codex implementer service could not be initialized."}, indent=2), file=sys.stderr)
            sys.exit(1)

        analysis_path = args.analysis_path or str(repo_root / "exports" / args.key / "codex_analysis" / "analysis_and_plan.md")
        
        payload = {
            "issue_key": args.key,
            "analysis_path": analysis_path,
            "issue_dir": str(repo_root / "exports" / args.key)
        }

        result = implementer_service.implement_plan(payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
