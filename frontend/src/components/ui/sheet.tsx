"use client";

import * as React from "react";
import { Dialog } from "radix-ui";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;

/** Bottom sheet, the primary overlay pattern on phones. */
export function SheetContent({
  title,
  description,
  children,
  className,
  full = false,
  hideTitle = false,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  full?: boolean;
  hideTitle?: boolean;
}) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="sheet-overlay fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px]" />
      <Dialog.Content
        aria-describedby={description ? undefined : undefined}
        className={cn(
          "sheet-content fixed inset-x-0 bottom-0 z-50 mx-auto flex w-full max-w-xl flex-col rounded-t-3xl border-t border-border bg-card pb-safe outline-none",
          full ? "top-0 rounded-none border-t-0 pt-safe" : "max-h-[92dvh]",
          className,
        )}
      >
        {!full && <div className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-muted-foreground/30" />}
        <div className={cn("flex items-center justify-between gap-3 px-4 pt-3 pb-2", hideTitle && "sr-only")}>
          <div className="min-w-0">
            <Dialog.Title className="truncate text-lg font-semibold">{title}</Dialog.Title>
            {description ? (
              <Dialog.Description className="text-[13px] text-muted-foreground">{description}</Dialog.Description>
            ) : (
              <Dialog.Description className="sr-only">{title}</Dialog.Description>
            )}
          </div>
          <Dialog.Close className="grid size-9 place-items-center rounded-full bg-elevated text-muted-foreground active:scale-95" aria-label="Close">
            <X className="size-4" />
          </Dialog.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </Dialog.Content>
    </Dialog.Portal>
  );
}
