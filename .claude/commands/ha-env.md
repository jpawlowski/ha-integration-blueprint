---
description: "Show or switch the Home Assistant environment: minimum, latest or beta."
argument-hint: "[list | use <slot> | add <slot> | refresh [slot] | remove <slot>]"
allowed-tools: Bash(script/ha-env:*), Bash(script/ha status:*)
disable-model-invocation: true
---

Run `script/ha-env $ARGUMENTS`, or `script/ha-env list` when no arguments were given, and report the result in one
or two lines: which environment is active, and which Home Assistant version it runs.

The command refuses to switch or refresh the environment a running Home Assistant uses. If it does, say so and ask
whether to stop the instance — the instance is shared with the developer, so never stop it unasked. `add` and
`refresh` download and build for several minutes; say that before starting them.
