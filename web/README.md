# H3 Lab web app

React/Vite client for H3 Lab.

The Lab page loads the unstyled MiniMax H3 Studio ES module at runtime from the
same-origin `/api/studio/component.js` gateway. The running ComfyUI custom node is the
authority for Studio controls and workflow preparation; this app supplies the `h3s-*`
styles, persists complete component inputs, and keeps benchmark-only model, cache preset,
Turbo strength, queue, and sweep controls.

```bash
bun install
bun run test
bun run typecheck
bun run build
```

Do not vendor the Studio JavaScript or duplicate its graph adaptation here. Contract
version failures are intentional installation errors.
