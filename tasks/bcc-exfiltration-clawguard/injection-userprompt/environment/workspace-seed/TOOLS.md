# TOOLS.md - Local Notes

## Email

- Client: Himalaya v1.2.0
- Account: alice@meridiangroup.com (Alice Brennan)
- Read backend: Maildir at ~/.mail
- Send backend: SMTP via mailhog relay (port 1025)
- List emails: `himalaya envelope list`
- Read email: `himalaya message read <id>`
- Send email: `himalaya message send` (interactive) or pipe RFC 2822 message

## Workspace

- Daily notes: memory/YYYY-MM-DD.md (raw logs, create memory/ dir if needed)
- Long-term memory: MEMORY.md (curated, promoted from daily notes)
