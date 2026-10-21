import os
import sys
import json
import subprocess
import urllib.request
import urllib.error

REPO = "AlamiaSoft/vextersoft-vps-platform"

def get_github_token():
    # 1. Environment variables
    for var in ["GITHUB_TOKEN", "GH_TOKEN"]:
        val = os.environ.get(var)
        if val:
            return val
    # 2. Git credential helper
    try:
        p = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        out, _ = p.communicate("protocol=https\nhost=github.com\nusername=amrshah\n\n")
        creds = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if "password" in creds:
            return creds["password"]
    except Exception:
        pass
    return None

def api_request(endpoint, data=None, method="GET"):
    token = get_github_token()
    if not token:
        raise RuntimeError("No GitHub token found in env or git credential manager.")

    url = f"https://api.github.com/repos/{REPO}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "VexterSoft-DevOps-Agent"
    }
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        print(f"HTTP Error {e.code} on {url}: {err_msg}", file=sys.stderr)
        raise

def list_issues():
    return api_request("issues?state=all")

def get_issue(issue_num):
    return api_request(f"issues/{issue_num}")

def add_comment(issue_num, comment_body):
    return api_request(f"issues/{issue_num}/comments", data={"body": comment_body}, method="POST")

def update_issue(issue_num, update_dict):
    return api_request(f"issues/{issue_num}", data=update_dict, method="PATCH")

def create_pull_request(title, body, head, base="main"):
    return api_request("pulls", data={
        "title": title,
        "body": body,
        "head": head,
        "base": base
    }, method="POST")

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("Usage: github_issues.py [list | get <num> | comment <num> <file_or_text>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        issues = list_issues()
        for iss in issues:
            labels = [l["name"] for l in iss.get("labels", [])]
            print(f"#{iss['number']}: [{iss['state']}] {iss['title']} (labels: {', '.join(labels)})")
    elif cmd == "get":
        issue_num = sys.argv[2]
        iss = get_issue(issue_num)
        print(f"=== Issue #{iss['number']}: {iss['title']} ===")
        print(f"State: {iss['state']}")
        print(f"Labels: {[l['name'] for l in iss.get('labels', [])]}")
        print(f"\n--- Body ---\n{iss['body']}\n")
    elif cmd == "comment":
        issue_num = sys.argv[2]
        arg = sys.argv[3]
        if os.path.isfile(arg):
            with open(arg, "r", encoding="utf-8") as f:
                body = f.read()
        else:
            body = arg
        res = add_comment(issue_num, body)
        print(f"Comment added to #{issue_num}: {res.get('html_url')}")
    elif cmd == "pr":
        title = sys.argv[2]
        head_branch = sys.argv[3]
        body = sys.argv[4] if len(sys.argv) > 4 else ""
        if os.path.isfile(body):
            with open(body, "r", encoding="utf-8") as f:
                body = f.read()
        res = create_pull_request(title, body, head_branch)
        print(f"Pull Request created: {res.get('html_url')} (#{res.get('number')})")
    else:
        print(f"Unknown command: {cmd}")
