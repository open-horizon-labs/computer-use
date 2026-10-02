# Progressive Spaces discovery

Use native tools by default; browser-only tasks prefer lightweight isolation. Use this path when the user requests a separate isolated desktop or selects Spaces. The separate cua-spaces MCP server exposes list_spaces, list_tools and call_tool. Lifecycle setup stays in the CLI; do not register the full upstream surface to obtain it.

Choose a concrete owned guest Space from fresh discovery. Never automatically choose a host, shared user desktop or another task's guest. If unavailable, return the setup problem; do not fall back to the host desktop. Credentials and provider configuration remain external.

Request list_tools with the Space and a task-relevant name filter. Inspect the returned exact schema and cache it within this task. Request another schema only when needed; never load the complete catalog or replace it with a giant instruction blob.

Use call_tool for Driver execution. Launch an isolated_new browser only in the chosen owned guest. Get a fresh window inventory and bind its exact PID/window to a task session. Use current target/tab IDs and freshly observed refs. Foreground delivery inside the dedicated guest is appropriate; it does not authorize host foreground use. Independently observe effects before reporting success. Do not replay uncertain input or use blind coordinates.

The three-tool grant reduces exposed metadata; it does not constrain every action behind call_tool. Driver permissions, guest ownership and user authorization still apply. Do not infer safety, correctness, speed or token savings from tool count.

Registration: cua mcp --embedded --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool. Embedded mode avoids starting a shared daemon merely for this optional connection. The CLI is /Users/muness1/.local/bin/cua. Explicit CLI lifecycle work may create/delete a task-owned Space; keep downloaded images unless the user requests their removal.
