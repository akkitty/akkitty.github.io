# Pudding Cup 2026: build stack and plan

_Written 2026-11-26. Library versions checked on npm the same day. Companion to [`pudding-research.md`](./pudding-research.md)._

**Goal:** a scroll-driven visual data story, published as a static site at `akkitty.github.io/<story-name>/`, submitted to the 2026 Pudding Cup by **Monday, Nov 30, 2026**.

**Approach:** use The Pudding's own stack (Svelte with Scrollama, written by Pudding staff) and compile it to plain static files for GitHub Pages. The topic hasn't been chosen yet, so the optional layer is picked once it is.

---

## 1. Core stack (used whatever the topic)

| Layer | Library | Version | Why |
|---|---|---|---|
| Framework | **Svelte** + **SvelteKit** | 5.59 / 3.4 | The Pudding's own stack. Each chart, step and widget is its own component; built-in tweening and transitions cover most animation. |
| Build | **Vite** | 8.4 | Comes with SvelteKit; instant reload while iterating. |
| Hosting | **@sveltejs/adapter-static** | 4.0 | Compiles the story to plain HTML/CSS/JS for GitHub Pages. No server. Sits next to the existing static pages in this repo. |
| Scroll steps | **Scrollama** | 3.2 | Russell Samora's library. Fires when a text block enters the screen, and reports progress within a step for scrubbed animations. |
| Sticky graphic | CSS `position: sticky` | — | The Pudding's recommended pattern: CSS pins the graphic, JavaScript only handles step changes. |
| Chart math | **D3**, only the parts needed (`d3-scale`, `d3-shape`, `d3-array`; maybe `d3-force`, `d3-geo`, `d3-delaunay`) | 7.9 | D3 does the math, Svelte draws the elements. |
| Data prep | Python (pandas) or Node scripts in `scripts/` | — | Raw data in, small JSON out, loaded at build time. Scripts and raw data get published, since the Cup rules encourage sharing process and raw materials. |
| QA | **Playwright** | — | Automated screenshots of every scroll step at phone and desktop widths. |

## 2. Optional, depending on the story

| If the story needs… | Use | Version | Notes |
|---|---|---|---|
| Thousands of animated marks (one per person, song, cover…) | Canvas 2D, or **Pixi.js** above ~5,000 marks | 8.23 | SVG slows down past a few thousand elements. Avoid three.js / heavy WebGL: *Life after death?* crashed a headless browser during research, and phones are less forgiving. |
| Choreographed sequences across many elements | **GSAP** | 3.15 | Only if Svelte's built-in animation isn't enough. Use one or the other, not both. |
| Sound (music, voices, data sonification) | **Tone.js** (generated sound) / **howler** (playing clips) | 15.1 / 2.2 | Muted by default with a visible toggle, as *Waveforms* and *Sounds of CDMX* do. |
| Maps | **MapLibre GL** | 6.19 | Free and needs no API token, unlike Mapbox. Only for a geographic story. |
| Quick exploratory or appendix charts | **@observablehq/plot** | 0.6 | For the methods section, not the main visuals. |
| Responsive chart scaffolding | **LayerCake** | 11.0 | Optional; hand-written Svelte components are often faster on a short build. |

**Not using:** scroll-smoothing or scroll-hijacking libraries such as Lenis. The Pudding's guidance is to monitor scrolling, never take it over.

## 3. Going beyond a click-through stepper

1. **A reader-input opening.** The reader guesses, draws or picks an answer first, then sees it compared with the real data (*Similes* quiz, *Kevin Bacon* guessing game, the "find yourself in the data" widgets Cup judges praised).
2. **The same marks change state as you scroll.** One sticky graphic whose dots move, regroup and recolor between steps, rather than a separate chart per step. This is where the "aha" moments come from.
3. **One signature interaction**, not a dashboard (bubble tea builder, draggable k-means centroids, ballot look-alike game).
4. **Personalization** where the data allows: "your city", "your birth year".
5. **A free-explore section at the end** for readers who want to dig in.
6. **Mobile done properly.**
   - Design mobile-first.
   - Calculate pixel heights from `window.innerHeight` rather than using `vh`.
   - Fall back to stacked static charts on small screens.
   - Respect `prefers-reduced-motion`.
7. **Accessibility.** A text description of every step, keyboard navigation, readable contrast.

**AI guardrail:** AI writes the code; the question, the self-collected data, the voice and the editorial judgment stay ours. That's the "heartbeat" the 2026 Cup page asks for. The methods section will include an honest AI-use note, as the 2025 *Benford's Law* winner did.

## 4. Project layout

```
akkitty.github.io/
  <story-name>/              ← built static output, served by GitHub Pages
  _src/<story-name>/         ← SvelteKit source
    scripts/                 ← data collection and cleaning (published with the story)
    src/lib/components/      ← Scrolly, StickyGraphic, Step, GuessWidget, Methods
    src/lib/charts/          ← one component per chart state
    static/data/             ← small JSON files the story loads
research/                    ← these notes
```

## 5. Schedule

| Day | Work |
|---|---|
| **Thu, Nov 26** | Choose the topic and question; start collecting data. |
| **Fri, Nov 27** | Analysis; storyboard the scroll steps and the signature interaction; set up the project and deploy a placeholder page. |
| **Sat, Nov 28** | Build the sticky scrolly graphic, step transitions and the reader-input opening. |
| **Sun, Nov 29** | Signature interaction, mobile layout, writing pass, methods and AI note. |
| **Mon, Nov 30** | Screenshot QA, accessibility pass, final deploy, **submit early** (the rules don't give a time zone). |

## 6. Topic checklist (from The Pudding's "Continue, Pivot, or Put It Down")

- [ ] Is the question unique, or does it at least take a new angle on a known topic?
- [ ] Can it be answered with data?
- [ ] Can we collect the data ourselves within about a day?
- [ ] Is it ethical to collect and use?
- [ ] Are the results actually interesting? If not, reframe the question rather than collecting more data.
- [ ] Is this our story to tell?
- [ ] Is there a one-line finding, or one data point to open on?

## Sources

- The Pudding, [Resources](https://pudding.cool/resources/):
  - [Responsive scrollytelling best practices](https://pudding.cool/process/responsive-scrollytelling/)
  - [Introducing Scrollama](https://pudding.cool/process/introducing-scrollama/)
  - [Scrollytelling with position: sticky](https://pudding.cool/process/scrollytelling-sticky/)
  - [D3 + Flexbox without SVG](https://pudding.cool/process/flexbox-layout/)
  - [Continue, Pivot, or Put It Down](https://pudding.cool/process/pivot-continue-down/)
  - [How to Make Dope Shit, Part 3](https://pudding.cool/process/how-to-make-dope-shit-part-3/)
- [The Pudding Cup](https://pudding.cool/pudding-cup/)
