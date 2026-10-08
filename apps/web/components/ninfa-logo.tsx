import Image from "next/image";
import type { Ref } from "react";

/** The OFFICIAL brand logo (Home UI V1, D6): the PNG from the approved reference package, copied
 * unchanged to `public/brand/ninfa-logo.png`. A brand-exact SVG is deferred - the prototype's
 * simplified traced SVG is never used as the logo. Intrinsic size 448x568. */
export const LOGO_SRC = "/brand/ninfa-logo.png";
const LOGO_WIDTH = 448;
const LOGO_HEIGHT = 568;

export interface NinfaLogoProps {
  className?: string;
  /** The `<img>` element itself - the logo transition measures and samples it. */
  imgRef?: Ref<HTMLImageElement>;
}

/** Purely decorative here (`alt=""`): wherever it is the only content of a control (the sidebar
 * link), that control carries its own accessible name. The rendered SIZE is always set by CSS
 * (`height`), never by the component. */
export function NinfaLogo({ className, imgRef }: NinfaLogoProps) {
  return (
    <Image
      ref={imgRef}
      className={className}
      src={LOGO_SRC}
      alt=""
      width={LOGO_WIDTH}
      height={LOGO_HEIGHT}
      unoptimized
      loading="eager"
      draggable={false}
    />
  );
}
