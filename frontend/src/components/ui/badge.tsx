import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-none", {
  variants: {
    variant: {
      default: "bg-accent text-accent-foreground",
      muted: "bg-muted text-muted-foreground",
      positive: "bg-positive/15 text-positive",
      negative: "bg-negative/15 text-negative",
      warning: "bg-warning/15 text-warning",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
