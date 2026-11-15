import type { ReactNode } from "react";

export type PageContainerMode = "reading" | "work" | "wide" | "fluid";

type PageContainerProps = {
  children: ReactNode;
  mode: PageContainerMode;
};

export default function PageContainer({ children, mode }: PageContainerProps) {
  return <div className={`sf-page-container sf-page-container--${mode}`} data-page-container-mode={mode}>{children}</div>;
}
