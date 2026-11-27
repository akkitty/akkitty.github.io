# CLAUDE.md

## Current project: 2026 Pudding Cup entry

We're building a visual, data-driven story to submit to The Pudding's 2026 Pudding Cup (https://pudding.cool/pudding-cup/). **Deadline: Monday, Nov 30, 2026.**

Read these before working on the project:

- `research/pudding-research.md`: research on The Pudding and the Cup (rules, past winners, judging patterns, what makes a Pudding story).
- `research/pudding-build-stack.md`: the agreed build stack (SvelteKit + Scrollama + D3, static output for GitHub Pages), optional libraries by story type, project layout, schedule and topic checklist.

## Conventions

- The story's source goes in `_src/<story-name>/`. The built static output goes in `<story-name>/` at the repo root, served by GitHub Pages.
- AI writes code; the question, data collection, voice and editorial judgment come from the user. Keep an honest AI-use note in the story's methods section.
- Network note: cloud sessions may block outside sites. pudding.cool and the hosts of the 2020–2025 Cup winners have been allowed in the environment.

## Rest of the repo

The other files at the root (`index.html`, the color pages, `drag-drop.js`, `password.js`, etc.) are an older, unrelated static site. Leave them alone unless asked.
