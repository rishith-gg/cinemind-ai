Continue CineMind development.
1. Read docs/PROGRESS.md, CLAUDE.md, and the next unfinished phase in docs/ROADMAP.md (or the phase named here: $ARGUMENTS).
2. Inspect the current implementation first. State a short plan (what, files, risks). 
3. Implement ONLY that phase, with tests alongside. Run `just check`, run the app, verify the feature works (Playwright MCP for UI).
4. Use the code-reviewer subagent on the diff and fix what it finds.
5. Update docs + PROGRESS.md, commit with Conventional Commits.
6. End with the Phase Report from CLAUDE.md. Do not start the next phase.
