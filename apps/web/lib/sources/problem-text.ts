import type { ImportProblem, SourceMethod } from "@ninfa/contracts";

import { sourcesCopy } from "./copy";
import type { FlowProblem } from "./use-import-flow";

/** The sentence for a problem, with what to do next where it helps. Never a technical word. */
export function problemText(problem: FlowProblem, method: SourceMethod): string {
  if (problem === "SOURCE_GONE") return sourcesCopy.errors.sourceGone;
  if (problem === "IMPORT_IN_PROGRESS") return sourcesCopy.errors.importInProgress;
  const base = sourcesCopy.problems[problem];
  const hints: Partial<Record<ImportProblem, Record<SourceMethod, string>>> = sourcesCopy.problemHints;
  const hint = hints[problem]?.[method];
  return hint ? `${base} ${hint}` : base;
}
