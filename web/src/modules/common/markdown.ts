/**
 * Remove HTML comments, repeating until stable so no `<!--` can survive
 * interleaved/nested markers (satisfies CodeQL's incomplete-sanitization check).
 * Used to strip author-guidance comments kept in the editable `.md` content files.
 */
export function stripHtmlComments(input: string): string {
  let previous;
  let output = input;
  do {
    previous = output;
    output = output.replace(/<!--[\s\S]*?-->/g, "");
  } while (output !== previous);
  return output;
}
