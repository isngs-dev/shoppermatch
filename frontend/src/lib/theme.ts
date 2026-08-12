import { useEffect, useState } from "react";

const THEME_KEY = "sm_theme";
type Theme = "light" | "dark";

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
}

export function initTheme() {
  const saved = (localStorage.getItem(THEME_KEY) as Theme) || "light";
  apply(saved);
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(THEME_KEY) as Theme) || "light"
  );

  useEffect(() => {
    apply(theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  return {
    theme,
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
}
