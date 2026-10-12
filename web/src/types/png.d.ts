// CI runs `tsc` without a Next build, so `next-env.d.ts` (which carries the
// image module types) is absent there. Same workaround as svg.d.ts.
declare module "*.png" {
  const content: import("next/image").StaticImageData;
  export default content;
}
