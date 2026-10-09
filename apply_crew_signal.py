#!/usr/bin/env python3
from pathlib import Path

coord = Path("backend/src/crew/coordinator.ts")
text = coord.read_text()
old = """export interface CrewDeps {
  model: string;
  supabase: SupabaseClient;
  courtListenerToken: string;
}
"""
new = """export interface CrewDeps {
  model: string;
  supabase: SupabaseClient;
  courtListenerToken: string;
  signal?: AbortSignal;
}

function abortedCrew(taskType: CrewTaskType): CrewOutput {
  return { reply: "", trace: { decision: "crew", taskType, rolesSpawned: [] }, authorities: [] };
}
"""
if "signal?: AbortSignal" not in text:
    if old not in text:
        raise SystemExit("CrewDeps missing")
    text = text.replace(old, new, 1)
old = """export async function runCrew(input: CrewInput, deps: CrewDeps): Promise<CrewOutput> {
  const taskType = detectTaskType(input);
"""
new = """export async function runCrew(input: CrewInput, deps: CrewDeps): Promise<CrewOutput> {
  const taskType = detectTaskType(input);
  if (deps.signal?.aborted) return abortedCrew(taskType);
"""
if "if (deps.signal?.aborted) return abortedCrew" not in text:
    if old not in text:
        raise SystemExit("runCrew start missing")
    text = text.replace(old, new, 1)
coord.write_text(text)
print("patched", coord)

route = Path("backend/src/routes/index.ts")
rt = route.read_text()
old = """            model,
            supabase: deps.supabase,
            courtListenerToken: deps.courtListenerToken,
          },
"""
new = """            model,
            supabase: deps.supabase,
            courtListenerToken: deps.courtListenerToken,
            signal: crewAbort.signal,
          },
"""
if "signal: crewAbort.signal" not in rt:
    if old not in rt:
        raise SystemExit("crew deps call missing")
    route.write_text(rt.replace(old, new, 1))
    print("patched", route)
else:
    print("route already passes signal")
