/** Clear so picking the same path again fires `change` (browser dedupes by value). */
export function resetFileInput(input: HTMLInputElement | null | undefined) {
  if (input) input.value = ''
}
