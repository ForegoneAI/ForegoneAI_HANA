import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps } from "react";

interface ButtonStyle {
  /** "primary" is the page's main action; "ghost" is everything else. */
  variant?: "primary" | "ghost";
  size?: "md" | "sm";
  /** Fill the width of the container (e.g. a form's submit button). */
  block?: boolean;
}

function buttonClass({ variant = "primary", size = "md", block = false }: ButtonStyle, extra?: string): string {
  return [
    "btn",
    variant === "ghost" && "btn--ghost",
    size === "sm" && "btn--sm",
    block && "btn--block",
    extra,
  ]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant,
  size,
  block,
  className,
  type = "button",
  ...props
}: ButtonStyle & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type={type} className={buttonClass({ variant, size, block }, className)} {...props} />;
}

/** A link that looks like a button, for actions that navigate. */
export function ButtonLink({ variant, size, block, className, ...props }: ButtonStyle & ComponentProps<typeof Link>) {
  return <Link className={buttonClass({ variant, size, block }, className)} {...props} />;
}
