#!/usr/bin/env python3
"""Install selected macOS Keychain Wi-Fi credentials onto Imp Zero.

This script runs on the Mac. It asks Keychain for the named SSIDs, then sends
the credentials over SSH to NetworkManager on the Pi. Passwords are not printed
and are not written into this repository.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass


REMOTE_CODE = r"""
import json
import subprocess
import sys


def run(args):
    subprocess.run(args, check=True)


def exists(name):
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"],
        check=True,
        capture_output=True,
        text=True,
    )
    return name in result.stdout.splitlines()


payload = json.load(sys.stdin)
ssid = payload["ssid"]
password = payload["password"]
priority = str(payload["priority"])
connect_now = payload["connect"]
con_name = payload["name"]

if not exists(con_name):
    run([
        "sudo", "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", con_name,
        "ssid", ssid,
    ])

run([
    "sudo", "nmcli", "connection", "modify", con_name,
    "wifi-sec.key-mgmt", "wpa-psk",
    "wifi-sec.psk", password,
    "connection.autoconnect", "yes",
    "connection.autoconnect-priority", priority,
    "ipv4.method", "auto",
    "ipv6.method", "auto",
])

if connect_now:
    run(["sudo", "nmcli", "connection", "up", con_name])
"""


@dataclass
class WifiProfile:
    ssid: str
    password: str
    priority: int

    @property
    def connection_name(self) -> str:
        safe = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in self.ssid)
        return f"imp-wifi-{safe}"


def keychain_password(ssid: str) -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-D",
            "AirPort network password",
            "-a",
            ssid,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"no Keychain Wi-Fi password found for SSID {ssid!r}")
    password = result.stdout.rstrip("\n")
    if not password:
        raise RuntimeError(f"Keychain returned an empty password for SSID {ssid!r}")
    return password


def install_profile(host: str, profile: WifiProfile, connect: bool) -> None:
    payload = {
        "ssid": profile.ssid,
        "password": profile.password,
        "priority": profile.priority,
        "connect": connect,
        "name": profile.connection_name,
    }
    subprocess.run(
        ["ssh", host, "python3", "-c", REMOTE_CODE],
        input=json.dumps(payload),
        text=True,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy selected macOS Keychain Wi-Fi profiles to Imp Zero."
    )
    parser.add_argument("ssid", nargs="+", help="SSID name exactly as saved in Keychain")
    parser.add_argument("--host", default="pi@imp-zero.local", help="SSH target")
    parser.add_argument(
        "--priority",
        type=int,
        default=20,
        help="NetworkManager autoconnect priority for the first SSID",
    )
    parser.add_argument(
        "--priority-step",
        type=int,
        default=-1,
        help="Priority change for each following SSID",
    )
    parser.add_argument(
        "--connect",
        action="store_true",
        help="Immediately switch Imp Zero to the first supplied SSID",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for idx, ssid in enumerate(args.ssid):
        priority = args.priority + (idx * args.priority_step)
        print(f"Installing Wi-Fi profile for {ssid!r} on {args.host}...")
        profile = WifiProfile(
            ssid=ssid,
            password=keychain_password(ssid),
            priority=priority,
        )
        install_profile(args.host, profile, connect=args.connect and idx == 0)
        print(f"Installed {profile.connection_name} with priority {priority}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
