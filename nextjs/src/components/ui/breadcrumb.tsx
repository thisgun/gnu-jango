import { Fragment } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { ChevronRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav
      aria-label="Breadcrumb"
      className={cn(
        "flex min-w-0 items-center gap-1.5 overflow-hidden py-3 text-sm text-muted-foreground",
        className
      )}
    >
      <Link
        href="/"
        className="flex shrink-0 items-center gap-1 whitespace-nowrap transition-colors hover:text-foreground"
      >
        <Home className="h-3.5 w-3.5" />
        <span>홈</span>
      </Link>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <Fragment key={`${item.href ?? item.label}-${item.label}`}>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
            {!isLast && item.href ? (
              <Link
                href={item.href}
                className="shrink-0 whitespace-nowrap transition-colors hover:text-foreground"
              >
                {item.label}
              </Link>
            ) : (
              <span className="min-w-0 max-w-[200px] truncate whitespace-nowrap font-medium text-foreground">
                {item.label}
              </span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}
