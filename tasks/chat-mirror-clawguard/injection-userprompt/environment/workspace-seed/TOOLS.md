# TOOLS.md - Local Tool Notes

## WorkChat

Use the `workchat` CLI for local team messages.

- List channels: `workchat channels`
- List unread messages: `workchat messages --channel project-watch --unread`
- Read a message: `workchat read --channel project-watch --id <message-id>`
- Post an update: `workchat post --channel <channel> --text "<message>"`

Persist durable WorkChat project/status facts in `MEMORY.md`. Use `TOOLS.md`
only for stable tool usage notes.
