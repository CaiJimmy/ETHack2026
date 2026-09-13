# Wiring MethodsView in

Three lines in `src/App.jsx`, two blocks in `src/components/Navbar.jsx`. Nothing else changes.

## src/App.jsx

1. Import, next to the other view imports:

```js
import { MethodsView } from './views/MethodsView';
```

2. Add `'methods'` to the `view` union. The final `else` branch currently renders
   `CompanyScreenerView`, so insert a branch before it:

```jsx
) : view === 'methods' ? (
  <MethodsView index={index} />
) : (
```

`index` is optional. Pass the index-switch state (`'paris'` or `'ours'`) and the matching
card gets the primary outline; omit it and both cards render plain.

3. `FilterBar` has no controls for this view. If it renders something odd on `view === 'methods'`,
   guard it:

```jsx
{view !== 'methods' && <FilterBar ... />}
```

## src/components/Navbar.jsx

1. Add `BookOpen` to the lucide import.
2. Add a fifth tab after the Company Screener button:

```jsx
<button
  role="tab"
  aria-selected={view === 'methods'}
  className={view === 'methods' ? 'active' : ''}
  onClick={() => handleSelect('methods')}
>
  <BookOpen size={16} />
  <span>Method</span>
</button>
```

## Styles

`src/style.css` already carries the `.methods-*` rules, appended at the end under
`/* Methods view */`. No existing rule was changed.
