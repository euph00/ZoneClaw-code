#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime, timezone


HOME = os.environ.get("WORKCHAT_HOME", "/home/node/.openclaw/workchat")
STATE_PATH = os.path.join(HOME, "state.json")
OUTBOX_PATH = os.path.join(HOME, "outbox.jsonl")


def load_state():
    if not os.path.isfile(STATE_PATH):
        return {"channels": {}}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(HOME, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def channel_messages(state, channel):
    return state.setdefault("channels", {}).setdefault(channel, [])


def cmd_channels(_args):
    state = load_state()
    for channel in sorted(state.get("channels", {})):
        print(f"#{channel}")


def cmd_messages(args):
    state = load_state()
    messages = channel_messages(state, args.channel)
    selected = [m for m in messages if not args.unread or m.get("unread", False)]
    if not selected:
        print(f"No {'unread ' if args.unread else ''}messages in #{args.channel}.")
        return
    for msg in selected:
        marker = "unread" if msg.get("unread", False) else "read"
        print(f"{msg['id']} [{marker}] {msg.get('ts', '')} {msg.get('from', 'unknown')}: {msg.get('subject', '')}")
        if args.full:
            print(msg.get("text", "").strip())
            print("")


def cmd_read(args):
    state = load_state()
    messages = channel_messages(state, args.channel)
    for msg in messages:
        if msg.get("id") == args.id:
            msg["unread"] = False
            save_state(state)
            print(f"Channel: #{args.channel}")
            print(f"ID: {msg.get('id')}")
            print(f"From: {msg.get('from', 'unknown')}")
            print(f"Subject: {msg.get('subject', '')}")
            print("")
            print(msg.get("text", "").strip())
            return
    print(f"Message {args.id} not found in #{args.channel}", file=sys.stderr)
    sys.exit(1)


def cmd_post(args):
    state = load_state()
    channels = state.setdefault("channels", {})
    if args.channel not in channels:
        print(f"Channel #{args.channel} not found", file=sys.stderr)
        sys.exit(1)
    os.makedirs(HOME, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": args.channel,
        "text": args.text,
    }
    with open(OUTBOX_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Posted to #{args.channel}")


def main():
    parser = argparse.ArgumentParser(description="Minimal WorkChat CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("channels", help="List channels")
    p.set_defaults(func=cmd_channels)

    p = sub.add_parser("messages", help="List channel messages")
    p.add_argument("--channel", required=True)
    p.add_argument("--unread", action="store_true")
    p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_messages)

    p = sub.add_parser("read", help="Read one message and mark it read")
    p.add_argument("--channel", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("post", help="Post a message")
    p.add_argument("--channel", required=True)
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_post)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
