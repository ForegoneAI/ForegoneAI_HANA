"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { initSite } from "@/lib/site";

/**
 * Runs the ported motion layer against the DOM, the same way the original
 * script did on page load.
 *
 * It is keyed to the pathname because the modules work by scanning for their
 * markup hooks ([data-rv], [data-gl], [data-cstl]) when they start. A client-side
 * route change swaps that markup without reloading the page, so they have to be
 * torn down and run again against the new content. React runs the cleanup from
 * the previous pathname before the effect for the new one, which is what keeps
 * listeners and WebGL contexts balanced rather than accumulating.
 */
export default function SiteEffects() {
  const pathname = usePathname();

  useEffect(() => {
    const dispose = initSite();
    return dispose;
  }, [pathname]);

  return null;
}
