/** URL prefix when the app is served from a sub-path (GitHub Pages: "/<repository>"). */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const withBase = (path: string) => `${BASE_PATH}${path}`;
