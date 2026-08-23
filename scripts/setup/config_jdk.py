#!/usr/bin/env python3
"""
SSH client for Termux interaction
Usage: python config_jdk.py [command]
"""
import sys
import paramiko

def ssh_exec(cmd, host='localhost', port=8022, user='u0_a413', password='termux123'):
    """Execute command on Termux via SSH"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(host, port=port, username=user, password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command(cmd)
        output = stdout.read().decode()
        error = stderr.read().decode()
        client.close()
        return output, error
    except Exception as e:
        return None, str(e)

if __name__ == '__main__':
    cmd = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'echo "SSH Connected!"'
    out, err = ssh_exec(cmd)
    if out:
        print(out)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
