---
name: privsep-role-bootstrap
description: "Select exact role-specific bootstrap context for privilege-separated agents"
metadata:
  {
    "openclaw":
      {
        "events": ["agent:bootstrap"]
      }
  }
---

# Privilege Separation Role Bootstrap

Replaces OpenClaw's default workspace bootstrap files with the exact file set
assigned to each experimental role.
