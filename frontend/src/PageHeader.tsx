import type { ReactNode } from "react";

export type PageHeaderMode = "standard" | "reading";

type PageHeaderProps = {
  title: string;
  description?: string;
  metadata?: ReactNode;
  actions?: ReactNode;
  mode?: PageHeaderMode;
  titleId?: string;
};

export default function PageHeader({
  title,
  description,
  metadata,
  actions,
  mode = "standard",
  titleId,
}: PageHeaderProps) {
  return <header className={`sf-page-header sf-page-header--${mode}`} aria-labelledby={titleId}>
    <div className="sf-page-header__identity">
      {metadata ? <div className="sf-page-header__metadata">{metadata}</div> : null}
      <h1 className="sf-page-header__title" id={titleId}>{title}</h1>
      {description ? <p className="sf-page-header__description">{description}</p> : null}
    </div>
    {actions ? <div className="sf-page-header__actions">{actions}</div> : null}
  </header>;
}
