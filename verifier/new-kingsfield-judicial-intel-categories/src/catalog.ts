import type { Catalog, FactualCategory, FactualId, MainId, TopId } from "./types";
import raw from "../data/catalog.json";

export const catalog = raw as Catalog;

export function factualById(id: FactualId): FactualCategory {
  const row = catalog.factual.find((f) => f.id === id);
  if (!row) throw new Error(`Unknown factual id ${id}`);
  return row;
}

export function factualByMain(main: MainId): FactualCategory[] {
  return catalog.factual.filter((f) => f.main === main);
}

export function factualByTop(top: TopId): FactualCategory[] {
  return catalog.factual.filter((f) => f.top === top);
}

export function offerList(): Array<{
  id: FactualId;
  name: string;
  sentence: string;
  main: string;
  top: string;
}> {
  const mainName = Object.fromEntries(catalog.main.map((m) => [m.id, m.name]));
  const topName = Object.fromEntries(catalog.top.map((t) => [t.id, t.name]));
  return catalog.factual.map((f) => ({
    id: f.id,
    name: f.name,
    sentence: f.sentence,
    main: mainName[f.main] ?? f.main,
    top: topName[f.top] ?? f.top,
  }));
}

if (catalog.top.length !== 3) throw new Error("catalog must have 3 top categories");
if (catalog.main.length !== 6) throw new Error("catalog must have 6 main categories");
if (catalog.factual.length !== 29) throw new Error("catalog must have 29 factual categories");
