export type JsonSchema = Readonly<Record<string, unknown>>;

export interface SchemaValidator {
  validate(schema: JsonSchema, value: unknown): ReadonlyArray<string>;
}

export function assertSchema(
  validator: SchemaValidator,
  schema: JsonSchema,
  value: unknown,
  boundary: "input" | "output"
): void {
  const errors = validator.validate(schema, value);
  if (errors.length) throw new Error(`SKILL_${boundary.toUpperCase()}_INVALID: ${errors.slice(0, 10).join("; ")}`);
}

export function sensitiveAnnotations(schema: JsonSchema): Readonly<Record<string, unknown>> {
  return Object.fromEntries(
    Object.entries(schema).filter(([key]) => key.startsWith("x-vav-"))
  );
}
