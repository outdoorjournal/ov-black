import type { Config } from "tailwindcss";
// Import (not require) the plugin: this config is loaded as ESM under Node 24,
// where a bare require() throws "require is not defined" and breaks the CSS
// compile. See types/tailwindcss-animate.d.ts for the ambient declaration.
import tailwindcssAnimate from "tailwindcss-animate";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        serif: ["var(--font-serif)", "Georgia", "ui-serif", "serif"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // OV Black semantic palette — preserved from S01.
        ink: "#0a0a0a",
        paper: "#f7f4ee",
        // OV signature accent — Outdoor Voyage burnt orange (#F5701F),
        // driven by --brand. Restrained punctuation only (CTAs, focus,
        // live/active states); see globals.css. The <alpha-value> slot lets
        // opacity modifiers (e.g. ring-brand/30) resolve correctly.
        brand: {
          DEFAULT: "hsl(var(--brand) / <alpha-value>)",
          foreground: "hsl(var(--brand-foreground) / <alpha-value>)",
        },
        // shadcn CSS-variable tokens — consumed by the generated primitives.
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // The OV Black micro-label rhythm. `eyebrow` is the widely-tracked
      // section/hero label; `label` is the slightly tighter caption/button.
      letterSpacing: {
        label: "0.3em",
        eyebrow: "0.4em",
      },
      // Editorial elevation scale. `sheet` = a light card on a light surface
      // (subtle); `float` / `float-lg` = a light card lifted off the dark
      // chrome (resting / raised).
      boxShadow: {
        sheet: "0 24px 70px -28px rgba(10, 10, 10, 0.35)",
        "sheet-lg": "0 32px 80px -30px rgba(10, 10, 10, 0.45)",
        float: "0 30px 80px -20px rgba(0, 0, 0, 0.6)",
        "float-lg": "0 40px 100px -20px rgba(0, 0, 0, 0.75)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
