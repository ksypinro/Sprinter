import argparse
import json
import sys
from pathlib import Path
from github_service.reviewer import GitReviewerService

def main():
    parser = argparse.ArgumentParser(description="Review a GitHub PR and post a review comment.")
    parser.add_argument("--key", required=True, help="Jira issue key (for artifact organization)")
    parser.add_argument("--pr-number", type=int, help="GitHub PR number")
    parser.add_argument("--commit-sha", help="Commit SHA to review")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")

    args = parser.parse_args()

    if not args.pr_number and not args.commit_sha:
        print(json.dumps({"error": "Either --pr-number or --commit-sha must be provided."}, indent=2), file=sys.stderr)
        sys.exit(1)

    try:
        repo_root = Path(args.repo_root).resolve()
        service = GitReviewerService.create(repo_root)
        
        payload = {
            "pr_number": args.pr_number,
            "commit_sha": args.commit_sha,
            "issue_dir": str(repo_root / "exports" / args.key)
        }

        result = service.review(args.key, payload)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
