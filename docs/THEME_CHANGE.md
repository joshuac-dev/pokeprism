# Copilot Instructions: Redo PokéPrism UI Themes with Catppuccin Latte and Frappé

You are working in `joshuac-dev/pokeprism`.

## Goal

Redo the frontend light and dark themes so that:

- Light mode uses **Catppuccin Latte**.
- Dark mode uses **Catppuccin Frappé**.
- The implementation follows Catppuccin’s official style guide:
  https://github.com/catppuccin/catppuccin/blob/main/docs/style-guide.md
- Do not change backend behavior, simulation behavior, API contracts, engine logic, card logic, or database code.
- This is a frontend theming/refactor task only.

The frontend is a React/Vite/Tailwind app in `frontend/`. It already uses `darkMode: 'class'` in `frontend/tailwind.config.js`, and `frontend/src/App.tsx` already toggles the `dark` class on `document.documentElement` based on `useUiStore().theme`.

## Important existing files to inspect first

Read these files before changing anything:

- `frontend/package.json`
- `frontend/tailwind.config.js`
- `frontend/src/index.css`
- `frontend/src/App.tsx`
- `frontend/src/stores/uiStore.ts`
- `frontend/src/components/layout/PageShell.tsx`
- `frontend/src/components/layout/TopBar.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- All files under:
  - `frontend/src/pages/`
  - `frontend/src/components/`

## Catppuccin palette values to use

Use these exact HEX values. Do not approximate and do not substitute Mocha or Macchiato.

### Latte, for light mode

```ts
const latte = {
  rosewater: '#dc8a78',
  flamingo: '#dd7878',
  pink: '#ea76cb',
  mauve: '#8839ef',
  red: '#d20f39',
  maroon: '#e64553',
  peach: '#fe640b',
  yellow: '#df8e1d',
  green: '#40a02b',
  teal: '#179299',
  sky: '#04a5e5',
  sapphire: '#209fb5',
  blue: '#1e66f5',
  lavender: '#7287fd',
  text: '#4c4f69',
  subtext1: '#5c5f77',
  subtext0: '#6c6f85',
  overlay2: '#7c7f93',
  overlay1: '#8c8fa1',
  overlay0: '#9ca0b0',
  surface2: '#acb0be',
  surface1: '#bcc0cc',
  surface0: '#ccd0da',
  base: '#eff1f5',
  mantle: '#e6e9ef',
  crust: '#dce0e8',
};
```

### Frappé, for dark mode

```ts
const frappe = {
  rosewater: '#f2d5cf',
  flamingo: '#eebebe',
  pink: '#f4b8e4',
  mauve: '#ca9ee6',
  red: '#e78284',
  maroon: '#ea999c',
  peach: '#ef9f76',
  yellow: '#e5c890',
  green: '#a6d189',
  teal: '#81c8be',
  sky: '#99d1db',
  sapphire: '#85c1dc',
  blue: '#8caaee',
  lavender: '#babbf1',
  text: '#c6d0f5',
  subtext1: '#b5bfe2',
  subtext0: '#a5adce',
  overlay2: '#949cbb',
  overlay1: '#838ba7',
  overlay0: '#737994',
  surface2: '#626880',
  surface1: '#51576d',
  surface0: '#414559',
  base: '#303446',
  mantle: '#292c3c',
  crust: '#232634',
};
```

## Catppuccin style-guide mapping

Follow the Catppuccin style guide’s intended usage:

- Main app background / page background: `base`
- Secondary panes, shell areas, sidebars, top bars: `mantle` or `crust`
- Cards, panels, modals, inputs, tables, console containers: `surface0`
- Elevated or hovered surfaces: `surface1`
- Stronger active/selected surface states: `surface2`
- Borders and separators: `surface1`, `surface2`, or `overlay0`
- Main text and headings: `text`
- Labels, secondary text, helper text: `subtext1` or `subtext0`
- Disabled/very subtle text: `overlay1`
- Links and primary actions: `blue`
- Active borders/focus rings: `lavender`
- Success states: `green`
- Warning states: `yellow`
- Error/destructive states: `red`
- Tags/pills/default badges: `blue`
- Cursor/terminal cursor/accent detail where relevant: `rosewater`
- Selection background: `overlay2` at roughly 20–30% opacity
- Text on colored accent backgrounds: choose the most legible color, usually `base` for Catppuccin accent buttons; legibility wins.

## Implementation strategy

Refactor the theme system around semantic tokens. Do not continue scattering hard-coded `slate-*`, `gray-*`, `zinc-*`, `neutral-*`, or raw hex colors throughout components.

### 1. Add Catppuccin CSS variables in `frontend/src/index.css`

Replace the minimal `index.css` with Tailwind imports plus a proper theme-token layer.

Use `:root` for Latte light mode and `.dark` for Frappé dark mode.

Prefer RGB triplet CSS variables, because Tailwind can then support opacity modifiers with `<alpha-value>`.

Example pattern:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    color-scheme: light;

    --ctp-rosewater: 220 138 120;
    --ctp-flamingo: 221 120 120;
    --ctp-pink: 234 118 203;
    --ctp-mauve: 136 57 239;
    --ctp-red: 210 15 57;
    --ctp-maroon: 230 69 83;
    --ctp-peach: 254 100 11;
    --ctp-yellow: 223 142 29;
    --ctp-green: 64 160 43;
    --ctp-teal: 23 146 153;
    --ctp-sky: 4 165 229;
    --ctp-sapphire: 32 159 181;
    --ctp-blue: 30 102 245;
    --ctp-lavender: 114 135 253;
    --ctp-text: 76 79 105;
    --ctp-subtext1: 92 95 119;
    --ctp-subtext0: 108 111 133;
    --ctp-overlay2: 124 127 147;
    --ctp-overlay1: 140 143 161;
    --ctp-overlay0: 156 160 176;
    --ctp-surface2: 172 176 190;
    --ctp-surface1: 188 192 204;
    --ctp-surface0: 204 208 218;
    --ctp-base: 239 241 245;
    --ctp-mantle: 230 233 239;
    --ctp-crust: 220 224 232;

    --app-bg: var(--ctp-base);
    --app-bg-secondary: var(--ctp-mantle);
    --app-bg-tertiary: var(--ctp-crust);
    --app-surface: var(--ctp-surface0);
    --app-surface-raised: var(--ctp-surface1);
    --app-surface-active: var(--ctp-surface2);
    --app-border: var(--ctp-surface2);
    --app-border-muted: var(--ctp-surface1);
    --app-text: var(--ctp-text);
    --app-text-muted: var(--ctp-subtext1);
    --app-text-subtle: var(--ctp-subtext0);
    --app-text-disabled: var(--ctp-overlay1);
    --app-primary: var(--ctp-blue);
    --app-primary-hover: var(--ctp-sapphire);
    --app-focus: var(--ctp-lavender);
    --app-success: var(--ctp-green);
    --app-warning: var(--ctp-yellow);
    --app-danger: var(--ctp-red);
    --app-accent: var(--ctp-mauve);
    --app-terminal-cursor: var(--ctp-rosewater);
  }

  .dark {
    color-scheme: dark;

    --ctp-rosewater: 242 213 207;
    --ctp-flamingo: 238 190 190;
    --ctp-pink: 244 184 228;
    --ctp-mauve: 202 158 230;
    --ctp-red: 231 130 132;
    --ctp-maroon: 234 153 156;
    --ctp-peach: 239 159 118;
    --ctp-yellow: 229 200 144;
    --ctp-green: 166 209 137;
    --ctp-teal: 129 200 190;
    --ctp-sky: 153 209 219;
    --ctp-sapphire: 133 193 220;
    --ctp-blue: 140 170 238;
    --ctp-lavender: 186 187 241;
    --ctp-text: 198 208 245;
    --ctp-subtext1: 181 191 226;
    --ctp-subtext0: 165 173 206;
    --ctp-overlay2: 148 156 187;
    --ctp-overlay1: 131 139 167;
    --ctp-overlay0: 115 121 148;
    --ctp-surface2: 98 104 128;
    --ctp-surface1: 81 87 109;
    --ctp-surface0: 65 69 89;
    --ctp-base: 48 52 70;
    --ctp-mantle: 41 44 60;
    --ctp-crust: 35 38 52;
  }

  html,
  body,
  #root {
    min-height: 100%;
  }

  body {
    @apply bg-app-bg text-app-text antialiased;
  }

  ::selection {
    background-color: rgb(var(--ctp-overlay2) / 0.28);
  }
}
```

Adjust details if needed, but keep the token architecture.

### 2. Update `frontend/tailwind.config.js`

Extend Tailwind colors using CSS variables. Keep `darkMode: 'class'`.

Add both raw Catppuccin tokens and semantic app tokens.

Use this pattern:

```js
colors: {
  ctp: {
    rosewater: 'rgb(var(--ctp-rosewater) / <alpha-value>)',
    flamingo: 'rgb(var(--ctp-flamingo) / <alpha-value>)',
    pink: 'rgb(var(--ctp-pink) / <alpha-value>)',
    mauve: 'rgb(var(--ctp-mauve) / <alpha-value>)',
    red: 'rgb(var(--ctp-red) / <alpha-value>)',
    maroon: 'rgb(var(--ctp-maroon) / <alpha-value>)',
    peach: 'rgb(var(--ctp-peach) / <alpha-value>)',
    yellow: 'rgb(var(--ctp-yellow) / <alpha-value>)',
    green: 'rgb(var(--ctp-green) / <alpha-value>)',
    teal: 'rgb(var(--ctp-teal) / <alpha-value>)',
    sky: 'rgb(var(--ctp-sky) / <alpha-value>)',
    sapphire: 'rgb(var(--ctp-sapphire) / <alpha-value>)',
    blue: 'rgb(var(--ctp-blue) / <alpha-value>)',
    lavender: 'rgb(var(--ctp-lavender) / <alpha-value>)',
    text: 'rgb(var(--ctp-text) / <alpha-value>)',
    subtext1: 'rgb(var(--ctp-subtext1) / <alpha-value>)',
    subtext0: 'rgb(var(--ctp-subtext0) / <alpha-value>)',
    overlay2: 'rgb(var(--ctp-overlay2) / <alpha-value>)',
    overlay1: 'rgb(var(--ctp-overlay1) / <alpha-value>)',
    overlay0: 'rgb(var(--ctp-overlay0) / <alpha-value>)',
    surface2: 'rgb(var(--ctp-surface2) / <alpha-value>)',
    surface1: 'rgb(var(--ctp-surface1) / <alpha-value>)',
    surface0: 'rgb(var(--ctp-surface0) / <alpha-value>)',
    base: 'rgb(var(--ctp-base) / <alpha-value>)',
    mantle: 'rgb(var(--ctp-mantle) / <alpha-value>)',
    crust: 'rgb(var(--ctp-crust) / <alpha-value>)',
  },
  app: {
    bg: 'rgb(var(--app-bg) / <alpha-value>)',
    bgSecondary: 'rgb(var(--app-bg-secondary) / <alpha-value>)',
    bgTertiary: 'rgb(var(--app-bg-tertiary) / <alpha-value>)',
    surface: 'rgb(var(--app-surface) / <alpha-value>)',
    surfaceRaised: 'rgb(var(--app-surface-raised) / <alpha-value>)',
    surfaceActive: 'rgb(var(--app-surface-active) / <alpha-value>)',
    border: 'rgb(var(--app-border) / <alpha-value>)',
    borderMuted: 'rgb(var(--app-border-muted) / <alpha-value>)',
    text: 'rgb(var(--app-text) / <alpha-value>)',
    textMuted: 'rgb(var(--app-text-muted) / <alpha-value>)',
    textSubtle: 'rgb(var(--app-text-subtle) / <alpha-value>)',
    textDisabled: 'rgb(var(--app-text-disabled) / <alpha-value>)',
    primary: 'rgb(var(--app-primary) / <alpha-value>)',
    primaryHover: 'rgb(var(--app-primary-hover) / <alpha-value>)',
    focus: 'rgb(var(--app-focus) / <alpha-value>)',
    success: 'rgb(var(--app-success) / <alpha-value>)',
    warning: 'rgb(var(--app-warning) / <alpha-value>)',
    danger: 'rgb(var(--app-danger) / <alpha-value>)',
    accent: 'rgb(var(--app-accent) / <alpha-value>)',
  },
}
```

Keep the old `surface` color alias only if removing it would create unnecessary churn, but prefer migrating usage to the new `app.*` and `ctp.*` tokens.

### 3. Refactor component class names

Search all frontend source files for hard-coded color utility classes, especially:

- `slate-*`
- `gray-*`
- `zinc-*`
- `neutral-*`
- `stone-*`
- `blue-*`
- `red-*`
- `yellow-*`
- `green-*`
- `white`
- `black`
- raw hex colors
- chart color literals
- inline SVG/fill/stroke colors
- Recharts color props
- D3 color usage
- xterm terminal theme configuration

Replace them with semantic app tokens where possible.

Examples:

- `bg-slate-100 dark:bg-slate-950` → `bg-app-bg`
- `bg-white dark:bg-slate-900` → `bg-app-bg-secondary`
- `border-slate-200 dark:border-slate-700` → `border-app-border`
- `text-slate-700 dark:text-slate-100` → `text-app-text`
- `text-slate-500 dark:text-slate-400` → `text-app-text-muted`
- `hover:bg-slate-100 dark:hover:bg-slate-800` → `hover:bg-app-surfaceRaised`
- `bg-blue-600 hover:bg-blue-500 text-white` → `bg-app-primary hover:bg-app-primaryHover text-ctp-base`
- `focus:ring-blue-500` → `focus:ring-app-focus`
- Warning boxes should use `ctp-yellow`.
- Error boxes should use `ctp-red`.
- Success boxes should use `ctp-green`.
- Info/link/primary states should use `ctp-blue`.
- Accent/highlight states may use `ctp-mauve`, `ctp-lavender`, `ctp-sapphire`, or `ctp-teal` depending on context, but stay within the Catppuccin palette.

Do not mechanically replace every `blue` with `app-primary` if a chart series or semantic state benefits from a distinct Catppuccin accent. Use the style guide’s meaning.

### 4. Refactor core layout first

Start with:

- `frontend/src/components/layout/PageShell.tsx`
- `frontend/src/components/layout/TopBar.tsx`
- `frontend/src/components/layout/Sidebar.tsx`

Expected direction:

- App background: `bg-app-bg`
- Sidebar/topbar: `bg-app-bg-secondary` or `bg-app-bg-tertiary`
- Borders: `border-app-border`
- Main text: `text-app-text`
- Muted nav text: `text-app-text-muted`
- Active nav item: `bg-app-primary text-ctp-base`
- Hover nav item: `hover:bg-app-surfaceRaised hover:text-app-text`
- Brand text: use `text-ctp-blue`, `text-ctp-mauve`, or a subtle gradient using Catppuccin accents only.

### 5. Refactor forms and controls

For inputs, textareas, selects, checkboxes, buttons, and filter controls:

- Background: `bg-app-surface`
- Hover/elevated background: `bg-app-surfaceRaised`
- Active/selected background: `bg-app-surfaceActive`
- Border: `border-app-border`
- Text: `text-app-text`
- Placeholder/help text: `text-app-text-subtle` or `placeholder:text-app-text-disabled`
- Focus ring: `focus:ring-app-focus`
- Primary button: `bg-app-primary hover:bg-app-primaryHover text-ctp-base`
- Destructive button: `bg-app-danger text-ctp-base` or outlined danger style if the solid version lacks contrast.
- Disabled controls: reduce opacity and use `text-app-text-disabled`.

Check contrast manually in both Latte and Frappé.

### 6. Refactor dashboards, charts, badges, tables, and heatmaps

For dashboard components and visualizations:

- Do not leave chart colors as raw browser defaults or arbitrary colors.
- Use Catppuccin accents consistently:
  - Primary series: `blue`
  - Secondary series: `mauve`
  - Tertiary series: `teal`
  - Positive: `green`
  - Warning/medium: `yellow` or `peach`
  - Negative: `red` or `maroon`
  - Neutral grid/axis lines: `overlay0`, `surface2`, or `surface1`
  - Text labels: `text`, `subtext1`, or `subtext0`
- For Recharts, D3, SVG, and canvas logic, prefer reading CSS variables at runtime or centralizing chart colors in a small helper module.
- Create a helper if needed, such as `frontend/src/theme/colors.ts`, that can read resolved CSS variables from `document.documentElement` and expose chart-safe `rgb(...)` strings.
- Avoid duplicating the full palette across many chart components.

### 7. Refactor terminal/live console styling

The app uses xterm dependencies, so inspect live console components carefully.

For terminal-like areas:

- Terminal background: `base`, `mantle`, or `crust` depending on nesting.
- Terminal text: `text`
- Cursor: `rosewater`
- Cursor text:
  - Latte: `base`
  - Frappé: `crust`
- Active border/focus: `lavender`
- Inactive border: `overlay0`
- ANSI-style semantic colors:
  - Red → `red`
  - Green → `green`
  - Yellow → `yellow`
  - Blue → `blue`
  - Magenta → `pink`
  - Cyan → `teal`
  - Black/gray → appropriate surface/subtext token
  - White → appropriate text/subtext token

### 8. Preserve behavior

Do not alter:

- Routes
- API calls
- Zustand store behavior except for very small safe improvements related to theme initialization
- Simulation setup logic
- Simulation live streaming logic
- History/memory/coverage data behavior
- Backend code

Theme toggling should continue to work through the existing `useUiStore` API.

### 9. Optional small improvement: theme initialization

If you see a flash of incorrect theme on first load, add a safe initialization improvement.

Acceptable options:

- Ensure the initial `dark` class is applied before React paints, based on `localStorage.theme`.
- Keep the default as dark if no theme is stored, because the current store defaults to dark.
- Do not introduce a complex theme system or OS-theme auto mode unless explicitly requested.

### 10. Validation

After refactoring, run:

```bash
cd frontend
npm install
npm run build
```

Also run any existing frontend lint/typecheck command if present. If no lint script exists, do not invent one.

Then inspect or reason through these views in both light and dark mode:

- New Simulation
- Live Simulation
- Dashboard
- History
- Memory
- Coverage
- Modals, filters, tables, charts, badges, forms, empty states, warning/error/success states

Verify:

- Light mode is clearly Catppuccin Latte.
- Dark mode is clearly Catppuccin Frappé, not Mocha.
- No component is stuck in Slate/gray colors.
- Text remains legible in both modes.
- Primary buttons, links, focus rings, warnings, errors, and success states follow the Catppuccin style guide.
- Charts and terminal/console areas use Catppuccin palette values.
- `npm run build` passes.

### 11. Final report

When finished, report:

1. Files changed.
2. Theme-token architecture added.
3. Major hard-coded color groups removed.
4. Any files intentionally left unchanged and why.
5. Build/typecheck results.
6. Any remaining visual risks or places that need manual browser review.
