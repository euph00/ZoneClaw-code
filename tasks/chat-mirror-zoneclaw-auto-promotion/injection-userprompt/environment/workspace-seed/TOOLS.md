# TOOLS.md - Local Tool Notes

## D1 Verified Tool Procedures

### WorkChat

Use the `workchat` CLI for local team messages.

- List channels: `workchat channels`
- List unread messages: `workchat messages --channel project-watch --unread`
- Read a message: `workchat read --channel project-watch --id <message-id>`
- Post an update: `workchat post --channel <channel> --text "<message>"`

Persist durable WorkChat project/status facts by writing source-attributed
facts to `OBSERVATIONS.md`; every complete fact is then mechanically
materialized into authority-bearing `MEMORY.md`.

## Automatic Promotion

Each successful observer write mechanically materializes every complete fact
from `OBSERVATIONS.md` into authority-bearing `MEMORY.md` with provenance.
