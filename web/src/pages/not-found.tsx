import { Link } from "react-router"

import { PageHeader, Section } from "@/components/page"
import { Button } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <>
      <PageHeader eyebrow="404" title="No such page" />
      <Section title="That URL does not lead anywhere">
        <p className="text-muted-foreground text-sm">
          A run you had open may have been deleted, or the link was typed by hand.
        </p>
        <div className="mt-3 flex gap-1.5">
          <Button size="sm" render={<Link to="/">Back to the lab</Link>} />
          <Button variant="outline" size="sm" render={<Link to="/runs">See every run</Link>} />
        </div>
      </Section>
    </>
  )
}
