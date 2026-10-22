#!/usr/bin/env python3
"""
Reusable GitHub API CLI helper using Git Credential Manager.

Resolves authentication dynamically from `git credential fill` without
storing, printing, or logging tokens. Supports reading issues, posting
protocol lifecycle comments, creating pull requests, and inspecting CI runs.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_OWNER = "AlamiaSoft"
DEFAULT_REPO = "vextersoft-vps-platform"
API_BASE = "https://api.github.com"


def get_github_token() -> str:
    """Retrieve GitHub token via git credential fill without logging secrets."""
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("Could not obtain GitHub token from git credential manager.")


def api_request(
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Perform an authenticated GitHub REST API v3 request."""
    token = get_github_token()
    url = f"{API_BASE}{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "vextersoft-vps-platform-gh-client")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {exc.code} for {method} {endpoint}: {err_body}") from exc


def cmd_issue_get(args: argparse.Namespace) -> int:
    for num in args.numbers:
        issue = api_request("GET", f"/repos/{args.owner}/{args.repo}/issues/{num}")
        print(f"=== ISSUE #{issue['number']}: {issue['title']} [{issue['state']}] ===")
        print(f"URL: {issue['html_url']}")
        labels = ", ".join(lbl["name"] for lbl in issue.get("labels", []))
        if labels:
            print(f"Labels: {labels}")
        print("\n" + (issue.get("body") or "(empty body)") + "\n")
        if args.comments:
            comments = api_request("GET", f"/repos/{args.owner}/{args.repo}/issues/{num}/comments")
            for idx, c in enumerate(comments, 1):
                print(f"--- Comment #{idx} by {c['user']['login']} at {c['created_at']} ---")
                print(c.get("body") or "")
                print()
    return 0


def cmd_issue_comment(args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body
    if not body or not body.strip():
        raise ValueError("Comment body cannot be empty.")
    res = api_request(
        "POST",
        f"/repos/{args.owner}/{args.repo}/issues/{args.number}/comments",
        {"body": body},
    )
    print(f"Posted comment on issue #{args.number}: {res['html_url']}")
    return 0


def cmd_pr_create(args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else (args.body or "")
    payload: dict[str, Any] = {
        "title": args.title,
        "head": args.head,
        "base": args.base,
        "body": body,
        "draft": bool(args.draft),
    }
    res = api_request("POST", f"/repos/{args.owner}/{args.repo}/pulls", payload)
    print(f"Created PR #{res['number']}: {res['html_url']}")
    return 0


def cmd_pr_list(args: argparse.Namespace) -> int:
    prs = api_request("GET", f"/repos/{args.owner}/{args.repo}/pulls?state={args.state}&per_page=20")
    for pr in prs:
        print(f"#{pr['number']} [{pr['state']}] {pr['title']} ({pr['head']['ref']} -> {pr['base']['ref']}) {pr['html_url']}")
    return 0


def cmd_runs_list(args: argparse.Namespace) -> int:
    res = api_request("GET", f"/repos/{args.owner}/{args.repo}/actions/runs?per_page={args.limit}")
    for run in res.get("workflow_runs", []):
        print(
            f"Run #{run['run_number']} | id={run['id']} | {run['name']} | "
            f"branch={run['head_branch']} | sha={run['head_sha'][:7]} | "
            f"status={run['status']} | conclusion={run['conclusion']} | {run['html_url']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub REST API helper for VexterSoft repository workflows")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_get = sub.add_parser("issue-get", help="Fetch one or more issues")
    p_get.add_argument("numbers", nargs="+", type=int)
    p_get.add_argument("--comments", action="store_true", help="Include issue comments")
    p_get.set_defaults(func=cmd_issue_get)

    p_comment = sub.add_parser("issue-comment", help="Post a comment on an issue")
    p_comment.add_argument("number", type=int)
    p_comment.add_argument("--body", help="Comment body string")
    p_comment.add_argument("--body-file", help="Path to markdown file containing comment body")
    p_comment.set_defaults(func=cmd_issue_comment)

    p_pr = sub.add_parser("pr-create", help="Create a pull request")
    p_pr.add_argument("--title", required=True)
    p_pr.add_argument("--head", required=True)
    p_pr.add_argument("--base", default="main")
    p_pr.add_argument("--body", help="PR body string")
    p_pr.add_argument("--body-file", help="Path to markdown file containing PR body")
    p_pr.add_argument("--draft", action="store_true")
    p_pr.set_defaults(func=cmd_pr_create)

    p_pr_list = sub.add_parser("pr-list", help="List pull requests")
    p_pr_list.add_argument("--state", default="open", choices=["open", "closed", "all"])
    p_pr_list.set_defaults(func=cmd_pr_list)

    p_runs = sub.add_parser("runs-list", help="List recent GitHub Actions workflow runs")
    p_runs.add_argument("--limit", type=int, default=10)
    p_runs.set_defaults(func=cmd_runs_list)

    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
