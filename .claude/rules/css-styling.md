# Frontend CSS Styling Conventions

## TailwindCSS First

Always prefer TailwindCSS utility classes over custom CSS. The project uses Tailwind via `@tailwind base/components/utilities` in `index.css`.

- **Do**: `<div className="flex items-center gap-4 p-6 text-gray-800">`
- **Don't**: Write custom CSS for layout, spacing, color, or typography that Tailwind already covers

## Custom CSS

Only write custom CSS in `index.css` (or a scoped stylesheet) when:

- A style cannot be achieved with Tailwind utilities (e.g., complex animations, pseudo-elements with dynamic values)
- A third-party library requires CSS overrides

Before reaching for custom CSS, check whether Tailwind's modifier syntax already covers the case:

- Placeholder text color: `placeholder:text-slate-blue` (not a custom `.form-input::placeholder` rule)
- Background opacity: `bg-navy/30` (not `rgba(0, 45, 114, 0.3)`)
- Focus ring: `focus:ring-2 focus:ring-sky-blue` (not a custom `:focus` rule)

Never use inline `style={{}}` props unless the value is genuinely dynamic and cannot be expressed as a Tailwind class.

### Custom Class Naming

When a custom class is necessary, use kebab-case and prefix it with `tm-` to avoid collisions with Tailwind-generated class names:

- **Do**: `tm-card-shimmer`, `tm-fade-in`
- **Don't**: `cardShimmer`, `anim1`, `shimmer`

## Class Ordering

Order Tailwind classes consistently within each element:

1. Layout/display (`flex`, `grid`, `block`, `hidden`)
2. Sizing (`w-*`, `h-*`, `min-h-*`, `max-w-*`)
3. Positioning (`relative`, `absolute`, `top-*`, `z-*`)
4. Spacing (`p-*`, `px-*`, `m-*`, `gap-*`)
5. Typography (`text-*`, `font-*`, `leading-*`, `tracking-*`)
6. Colors & backgrounds (`bg-*`, `text-*` color, `border-*`)
7. Borders & radius (`border`, `rounded-*`)
8. Effects & transitions (`shadow-*`, `opacity-*`, `transition`, `hover:*`)

## Responsive Design

Use Tailwind's mobile-first breakpoint prefixes. Start with the mobile layout, then layer larger breakpoints:

```tsx
<div className="flex flex-col gap-4 md:flex-row md:gap-8 lg:gap-12">
```

Standard breakpoints in use: `sm` (640px), `md` (768px), `lg` (1024px), `xl` (1280px).

## Spacing & Sizing

Use Tailwind's spacing scale (multiples of 4px). Avoid arbitrary values like `p-[13px]` unless there is no equivalent.

- Prefer: `p-4` (16px), `gap-6` (24px), `mt-8` (32px)
- Avoid: `p-[13px]`, `mt-[30px]`

## Colors & Typography

Use Tailwind's default palette or custom colors defined in `tailwind.config.js`. Do not hardcode hex values in class names (e.g. `text-[#abc123]`) — if a color is needed and not in the default palette, add it to the Tailwind config as a named token and use that instead.

Typography scale:
- Page headings: `text-2xl font-bold` or larger
- Section headings: `text-xl font-semibold`
- Body text: `text-base` (default)
- Supporting/meta text: `text-sm text-gray-500`

## Component Styling Patterns

- Apply styles directly on JSX elements with `className`; do not use a separate stylesheet per component
- Extract repeated class combinations into a well-named component rather than copying long class strings
- Do not use `@apply` in CSS files — compose utilities directly in JSX instead
