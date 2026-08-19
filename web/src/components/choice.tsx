import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

export function Choice({
  value,
  options,
  onChange,
  render = (item: string) => item,
  placeholder = "choose",
  label,
  emptyLabel,
  size,
  className,
}: {
  value: string
  options: string[]
  onChange: (value: string) => void
  render?: (value: string) => string
  placeholder?: string
  label?: string
  emptyLabel?: string
  size?: "sm" | "default"
  className?: string
}) {
  const present = value && !options.includes(value) ? [value, ...options] : options
  const items = [
    ...(emptyLabel ? [{ value: "", label: emptyLabel }] : []),
    ...present.filter(Boolean).map((option) => ({ value: option, label: render(option) })),
  ]

  return (
    <Select value={value} onValueChange={(next) => onChange(String(next ?? ""))} items={items}>
      <SelectTrigger
        size={size}
        aria-label={label ?? placeholder}
        className={cn("w-full min-w-0", className)}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value || "__empty"} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
