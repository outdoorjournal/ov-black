import type { Metadata } from "next";
import type { ReactNode } from "react";

import { resolvePublicEnv } from "@/lib/env";
import "./globals.css";

export const metadata: Metadata = {
  title: "OV Black",
  description: "By invitation only.",
};

// Public config is injected at request time (not baked at build), so the layout
// must render dynamically — otherwise a static prerender would freeze an empty
// window.__OVB_ENV__ into the HTML. The app is auth-gated and effectively
// dynamic already; this only opts the few prototype pages out of static export.
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  // Read once on the server (runtime) and hand the browser its public config via
  // an inline script that runs before any client component hydrates. Escape `<`
  // so a value can never break out of the <script> element.
  const publicEnvJson = JSON.stringify(resolvePublicEnv()).replace(
    /</g,
    "\\u003c",
  );
  return (
    <html lang="en">
      <body className="bg-paper text-ink">
        <script
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{
            __html: `window.__OVB_ENV__=${publicEnvJson}`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
