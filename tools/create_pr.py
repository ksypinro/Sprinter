import argparse
import json
import sys
from pathlib import Path
from github_service.pusher import GitPusherService

def main():
    parser = argparse.ArgumentParser(description="Create a git branch, commit changes, and open a GitHub PR.")
    parser.add_argument("--key", required=True, help="Jira issue key")
    parser.add_argument("--commit-log", help="Path to the commit_log.md file")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")

    args = parser.parse_args()

    try:
        repo_root = Path(args.repo_root).resolve()
        service = GitPusherService.create(repo_root)
        
        commit_log_path = args.commit_log or str(repo_root / "exports" / args.key / "codex_implementation" / "commit_log.md")
        
        payload = {
            "issue_key": args.key,
            "commit_log_path": commit_log_path,
            "issue_dir": str(repo_root / "exports" / args.key)
        }

        result = service.create_pull_request(args.key, "tool-pr", payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
