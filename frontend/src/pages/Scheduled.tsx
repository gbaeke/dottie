import { useQuery } from '@tanstack/react-query'
import { CalendarClock } from 'lucide-react'
import { listAllOptions, listDottiesOptions } from '@/client/@tanstack/react-query.gen'
import { ScheduleRow } from '@/components/ScheduleRow'
import { EmptyState, ListSkeleton, Page, PageTitle } from '@/components/ui'

export function Scheduled() {
  const schedules = useQuery(listAllOptions())
  const dotties = useQuery(listDottiesOptions())
  return (
    <Page>
      <PageTitle
        title="Scheduled"
        sub="What your dotties do on their own. The clock wakes them; they sleep in between."
      />
      {schedules.isPending && <ListSkeleton />}
      {schedules.data?.length === 0 && (
        <EmptyState icon={<CalendarClock className="size-6" />} title="Nothing scheduled">
          Open a dottie's Schedules tab to set up a morning briefing, a weekly review or a reminder. A dottie can also
          schedule things for itself when you ask it in chat.
        </EmptyState>
      )}
      <ul className="space-y-3">
        {schedules.data?.map((s) => (
          <ScheduleRow key={s.id} s={s} showDottie hue={dotties.data?.find((d) => d.id === s.dottie_id)?.hue ?? 265} />
        ))}
      </ul>
    </Page>
  )
}
