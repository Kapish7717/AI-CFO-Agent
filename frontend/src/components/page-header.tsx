import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 border-b border-border px-6 py-8 md:flex-row md:items-end md:justify-between md:px-10">
      <div className="max-w-2xl">
        {eyebrow && (
          <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">{eyebrow}</p>
        )}
        <h1 className="mt-2 font-display text-4xl md:text-5xl text-foreground">{title}</h1>
        {description && (
          <p className="mt-3 text-sm text-muted-foreground leading-relaxed">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
