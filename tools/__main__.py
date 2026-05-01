import sys
import argparse
import importlib
import json

TOOLS = [
    "export_issue",
    "create_issue",
    "analyze_issue",
    "implement_plan",
    "create_pr",
    "review_pr",
    "workflow_status",
    "workflow_control",
]

def main():
    parser = argparse.ArgumentParser(
        prog="python -m tools",
        description="Sprinter Individual CLI Tools",
    )
    parser.add_argument("tool", choices=TOOLS, help="The tool to run", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the tool")

    args = parser.parse_args()

    if not args.tool:
        print("Available tools:")
        for tool in TOOLS:
            print(f"  - {tool}")
        sys.exit(0)

    try:
        module = importlib.import_module(f"tools.{args.tool}")
        # Patch sys.argv so the sub-tool thinks it's being called directly
        sys.argv = [f"python -m tools {args.tool}"] + args.args
        module.main()
    except ImportError as e:
        print(json.dumps({"error": f"Could not import tool {args.tool}: {str(e)}"}, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
