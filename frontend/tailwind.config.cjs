/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          950: "#1e1b4b",
        },
        accent: {
          50: "#ecfeff",
          100: "#cffafe",
          200: "#a5f3fc",
          300: "#67e8f9",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
          800: "#155e75",
          900: "#164e63",
          950: "#083344",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 6px -1px rgb(0 0 0 / 0.06)",
        glow: "0 8px 30px -8px rgb(99 102 241 / 0.45)",
        "glow-lg": "0 20px 60px -12px rgb(99 102 241 / 0.5)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #4f46e5 0%, #6366f1 45%, #06b6d4 100%)",
        "mesh-light":
          "radial-gradient(at 15% 0%, rgb(199 210 254 / 0.55) 0px, transparent 55%), radial-gradient(at 85% 15%, rgb(165 243 252 / 0.5) 0px, transparent 50%), radial-gradient(at 50% 100%, rgb(224 231 255 / 0.6) 0px, transparent 55%)",
        "mesh-dark":
          "radial-gradient(at 15% 0%, rgb(79 70 229 / 0.25) 0px, transparent 55%), radial-gradient(at 85% 10%, rgb(8 145 178 / 0.22) 0px, transparent 50%), radial-gradient(at 50% 100%, rgb(49 46 129 / 0.35) 0px, transparent 55%)",
      },
      keyframes: {
        "gradient-x": {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        "pop-in": {
          "0%": { opacity: "0", transform: "scale(0.96) translateY(4px)" },
          "100%": { opacity: "1", transform: "scale(1) translateY(0)" },
        },
      },
      animation: {
        "gradient-x": "gradient-x 6s ease infinite",
        "pop-in": "pop-in 0.15s ease-out",
      },
      backgroundSize: {
        "gradient-size": "200% 200%",
      },
    },
  },
  plugins: [],
};
