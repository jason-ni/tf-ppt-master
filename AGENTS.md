# AGENTS.md

This file is the project entry point for general AI agents.

**You MUST read [`skills/tf-ppt-master/SKILL.md`](skills/tf-ppt-master/SKILL.md) before any PPT generation task or repo modification.** It owns global execution discipline and points to the route selector; after routing, the selected runtime authority owns its steps, gates, and commands.

**Repository execution anchor**: resolve the absolute repository root from this
file's supplied path and retain the absolute `skills/tf-ppt-master` root before the
first command. Paths in this file are repository-relative notation only; invoke
them through those absolute roots, retain the absolute project path returned by
initialization, and never issue `cd skills/tf-ppt-master` or `cd projects/...`.
When parsing machine-readable stdout, keep stderr separate and never place
`2>&1` upstream of a JSON or XML parser. Invoke each such command once per
concrete argument set; never encode its executable or flag list in scalar shell
strings, batch it through a shell loop, or add a downstream parser when the
command provides a compact view.

## Project Overview

TF PPT Master turns source material into natively editable DrawingML PPTX.

This skill is tightly coupled with `tf-assistant` and `pptx-viewer`. When in development, we can use codebase-memory-mcp to inspect these two codebase for hidden details.

<br />

`tf-assistant` provides a MCP service `tf-assistant-pptx` for agents.  `pptx-viewer` hosts the codebase for pptx parsing and editing.
