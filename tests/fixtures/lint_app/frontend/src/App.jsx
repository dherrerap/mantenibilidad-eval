// Fixture: JSX in a .jsx file must parse; the `eslint-disable` comment must not hide the report (allowInlineConfig: false).
export default function App({ items, mode }) {
  // eslint-disable-next-line no-mixed-operators
  const show = items && mode || false;
  return <ul>{show && items.map((i) => <li key={i}>{i}</li>)}</ul>;
}
