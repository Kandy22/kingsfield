/**
 * Operator-set cap on output tokens per model step, from LLM_MAX_OUTPUT_TOKENS.
 * Returns undefined when it is unset or unusable (empty, zero, negative, a
 * fraction or not a number), so a bad value is ignored instead of being sent
 * upstream. Port of Mike upstream 171d6f9, which replaced one hard-coded
 * 16,384 shared by every model with "provider decides unless the operator sets
 * a limit".
 */
export function maxOutputTokensOverride(): number | undefined {
  const value = Number(process.env.LLM_MAX_OUTPUT_TOKENS);
  return Number.isSafeInteger(value) && value > 0 ? value : undefined;
}
