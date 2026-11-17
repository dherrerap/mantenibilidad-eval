// Fixture: TypeScript syntax (type assertion with angle brackets, which is not valid JSX) must parse.
export function size(value: unknown): number {
  const s = <string>value;
  return s.length;
}
