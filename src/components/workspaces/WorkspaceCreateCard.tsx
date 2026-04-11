"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Cat, Dog, LoaderCircle, Plus, UserRound } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const fieldClassName =
  "w-full rounded-2xl border border-black/10 bg-white/80 px-4 py-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15";

const speciesOptions = [
  { value: "human" as const, label: "Human", icon: UserRound },
  { value: "dog" as const, label: "Dog", icon: Dog },
  { value: "cat" as const, label: "Cat", icon: Cat },
];

interface WorkspaceCreateCardProps {
  className?: string;
  title?: string;
  onCreated?: () => void;
}

export default function WorkspaceCreateCard({
  className,
  title = "New workspace",
  onCreated,
}: WorkspaceCreateCardProps) {
  const router = useRouter();
  const [isRouting, startTransition] = useTransition();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [species, setSpecies] = useState<"human" | "dog" | "cat">("dog");

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const workspace = await api.createWorkspace({
        displayName: displayName.trim(),
        species,
      });

      onCreated?.();
      startTransition(() => {
        router.push(`/workspaces/${workspace.id}/ingestion`);
        router.refresh();
      });
    } catch (submissionError) {
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "Unable to create workspace"
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card
      className={cn(
        "border-0 bg-white/80 py-6 shadow-[0_24px_80px_-40px_rgba(24,34,28,0.45)] ring-1 ring-black/8 backdrop-blur-sm",
        className
      )}
    >
      <CardHeader className="px-6">
        <CardTitle className="text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-6">
        <form
          className="space-y-4"
          onSubmit={handleSubmit}
          data-testid="workspace-create-form"
        >
          <div
            className="grid gap-3 sm:grid-cols-3"
            role="group"
            aria-label="Species"
          >
            {speciesOptions.map((option) => {
              const Icon = option.icon;
              const isSelected = option.value === species;

              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setSpecies(option.value)}
                  data-testid={`workspace-species-${option.value}`}
                  className={cn(
                    "flex flex-col items-center gap-2 rounded-2xl border px-4 py-3 transition",
                    isSelected
                      ? "border-emerald-600 bg-emerald-50 text-emerald-950 shadow-[inset_0_0_0_1px_rgba(5,150,105,0.14)]"
                      : "border-black/8 bg-white/70 text-slate-700 hover:border-black/15 hover:bg-white"
                  )}
                >
                  <Icon className="size-5" />
                  <span className="text-sm font-semibold">{option.label}</span>
                </button>
              );
            })}
          </div>

          <input
            required
            aria-label="Workspace name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            data-testid="workspace-name-input"
            className={fieldClassName}
            placeholder="e.g. Rosie baseline"
          />

          {error && (
            <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button
            type="submit"
            size="lg"
            className="w-full bg-emerald-500 text-emerald-950 hover:bg-emerald-400"
            disabled={isSubmitting || isRouting || !displayName.trim()}
            data-testid="workspace-create-submit"
          >
            {isSubmitting || isRouting ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Plus className="size-4" />
            )}
            Create
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
