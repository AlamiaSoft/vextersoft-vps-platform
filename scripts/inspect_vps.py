import os
import sys
import paramiko

def load_env():
    env = {}
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env

def main():
    env = load_env()
    ip = env.get("VPS_IP")
    user = env.get("SSH_USERNAME", "root")
    password = env.get("SSH_PASSWORD")

    if not ip or not password:
        print("Error: VPS_IP or SSH_PASSWORD missing in .env")
        sys.exit(1)

    print(f"Connecting to VPS at {ip} as {user}...")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=ip,
            port=22,
            username=user,
            password=password,
            timeout=15,
            banner_timeout=30,
            look_for_keys=False,
            allow_agent=False
        )
        print("Connected successfully!")
    except Exception as e:
        print(f"SSH Connection Failed: {e}")
        sys.exit(1)

    commands = [
        ("OS Architecture & Kernel", "uname -a"),
        ("OS Release Details", "cat /etc/os-release"),
        ("CPU Info", "lscpu"),
        ("Memory & Swap", "free -h"),
        ("Block Devices", "lsblk -f"),
        ("Disk Usage & Filesystems", "df -hT"),
        ("Network Interfaces", "ip -br addr"),
        ("Routing Table", "ip route"),
        ("DNS Resolvers", "cat /etc/resolv.conf"),
        ("Listening Sockets & Ports", "ss -tulpn"),
        ("Firewall (UFW Status)", "ufw status verbose || echo 'ufw not active or not installed'"),
        ("Firewall (iptables rules)", "iptables -S"),
        ("Running Services", "systemctl list-units --type=service --state=running --no-pager"),
        ("Installed Packages (Docker/Web/Security)", "dpkg -l | grep -E 'docker|containerd|nginx|apache|caddy|certbot|ufw|fail2ban|cloud-init' || echo 'No matches'"),
        ("Active Shell Users", "grep -E 'sh$' /etc/passwd"),
        ("SSH Active Configuration", "sshd -T | grep -E 'port|permitrootlogin|passwordauthentication|pubkeyauthentication|x11forwarding|maxauthtries|ciphers|macs' || true"),
        ("Recent Logins", "last -n 5"),
    ]

    results = []
    for title, cmd in commands:
        print(f"Executing: {title} ({cmd})...")
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()

        section = f"================================================================================\n"
        section += f"SECTION: {title}\n"
        section += f"COMMAND: {cmd}\n"
        section += f"================================================================================\n"
        if out:
            section += f"[STDOUT]\n{out}\n"
        if err:
            section += f"[STDERR]\n{err}\n"
        section += "\n"
        results.append(section)

    client.close()

    output_path = os.path.join("docs", "vps-inspection-raw.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(results)

    print(f"\nInspection completed. Results written to {output_path}")

if __name__ == "__main__":
    main()
