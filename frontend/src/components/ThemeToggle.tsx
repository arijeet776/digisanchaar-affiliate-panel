import { useTheme } from "../theme/ThemeContext";
import { IconMoon, IconSun } from "./Icons";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="qx-theme-toggle" role="group" aria-label="Theme" data-testid="theme-toggle">
      <button
        type="button"
        aria-label="Dark mode"
        aria-pressed={theme === "dark"}
        className={theme === "dark" ? "active" : ""}
        onClick={() => setTheme("dark")}
      >
        <IconMoon width={14} height={14} />
      </button>
      <button
        type="button"
        aria-label="Light mode"
        aria-pressed={theme === "light"}
        className={theme === "light" ? "active" : ""}
        onClick={() => setTheme("light")}
      >
        <IconSun width={14} height={14} />
      </button>
    </div>
  );
}
