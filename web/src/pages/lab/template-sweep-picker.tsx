import { useMemo, useState } from "react"

import type { StudioTemplateCatalog } from "@/lib/studio-runtime"
import {
  CURRENT_TEMPLATE_ID,
  templateRequirementFailures,
} from "./sweep-options"

export function TemplateSweepPicker({
  catalog,
  selected,
  inputs,
  capabilities,
  onChange,
}: {
  catalog: StudioTemplateCatalog
  selected: (string | number | boolean)[]
  inputs: Record<string, unknown>
  capabilities: Record<string, unknown>
  onChange: (selected: string[]) => void
}) {
  const [query, setQuery] = useState("")
  const picked = new Set(selected.map(String))
  const categoryNames = useMemo(
    () => new Map(catalog.categories.map((category) => [category.id, category.name])),
    [catalog.categories]
  )
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const filtered = catalog.templates.filter((template) => {
    const haystack = [
      template.name,
      categoryNames.get(template.category),
      template.description,
      template.tradeoff,
      template.evidence,
      ...template.tags,
    ]
      .join(" ")
      .toLowerCase()
    return terms.every((term) => haystack.includes(term))
  })

  const toggle = (id: string) => {
    onChange(
      picked.has(id)
        ? [...picked].filter((value) => value !== id)
        : [...picked, id]
    )
  }

  return (
    <div className="border-rule space-y-2 rounded-sm border bg-black/10 p-2">
      <input
        data-template-axis-search
        aria-label="Search template axis"
        type="search"
        value={query}
        placeholder={catalog.selector.placeholder}
        onChange={(event) => setQuery(event.target.value)}
        className="border-rule bg-ink text-bone w-full rounded-sm border px-2 py-1.5 text-sm outline-none focus:border-current"
      />
      <button
        type="button"
        data-template-axis-current
        aria-pressed={picked.has(CURRENT_TEMPLATE_ID)}
        onClick={() => toggle(CURRENT_TEMPLATE_ID)}
        className={
          picked.has(CURRENT_TEMPLATE_ID)
            ? "border-signal/60 bg-signal/15 text-signal w-full rounded-sm border px-2 py-1.5 text-left text-xs"
            : "border-rule text-muted-foreground hover:text-bone w-full rounded-sm border px-2 py-1.5 text-left text-xs"
        }
      >
        Current settings
      </button>
      <div className="max-h-96 space-y-3 overflow-y-auto pr-1">
        {catalog.categories.map((category) => {
          const templates = filtered.filter(
            (template) => template.category === category.id
          )
          if (!templates.length) return null
          return (
            <section
              key={category.id}
              data-template-axis-category={category.id}
              className="space-y-1"
            >
              <h4 className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wider">
                {category.name}
              </h4>
              {templates.map((template) => {
                const failures = templateRequirementFailures(
                  template,
                  inputs,
                  capabilities
                )
                const on = picked.has(template.id)
                return (
                  <button
                    key={template.id}
                    type="button"
                    data-template-axis-id={template.id}
                    disabled={failures.length > 0}
                    aria-pressed={on}
                    onClick={() => toggle(template.id)}
                    className={
                      on
                        ? "border-signal/60 bg-signal/10 text-bone w-full rounded-sm border p-2 text-left"
                        : "border-rule text-muted-foreground hover:border-rule/80 hover:text-bone w-full rounded-sm border p-2 text-left disabled:cursor-not-allowed disabled:opacity-55"
                    }
                  >
                    <span className="flex items-center justify-between gap-2 text-xs font-semibold">
                      <span>{template.name}</span>
                      <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[9px] uppercase">
                        {template.evidence}
                      </span>
                    </span>
                    <span className="mt-1 block text-[11px]">{template.description}</span>
                    <span className="mt-0.5 block text-[10px] opacity-70">
                      {template.tradeoff}
                    </span>
                    <span className="mt-1 block text-[9px] opacity-60">
                      {template.tags.join(" · ")}
                    </span>
                    {failures.length ? (
                      <span className="text-signal mt-1 block text-[10px]">
                        {failures.join(" ")}
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </section>
          )
        })}
      </div>
      {filtered.length === 0 ? (
        <p className="text-muted-foreground text-xs">No templates match this search.</p>
      ) : null}
    </div>
  )
}
