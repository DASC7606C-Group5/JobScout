import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { JobTracking } from '../components/career/job-tracking'
import { PageHeading } from '../components/layout/page-heading'
import { useApplications } from '../state/career-queries'

export const Route = createFileRoute('/_workspace/tracked')({ component: TrackedPage })
function TrackedPage() {
  const query = useApplications()
  const [stage, setStage] = useState('all')
  return (
    <>
      <PageHeading
        eyebrow="TRACKED JOBS"
        title="Application progress"
        description="Progress is shared across tasks and survives deleting a search."
      />
      <label className="label" htmlFor="tracked-stage">
        Filter by stage
      </label>
      <select
        id="tracked-stage"
        className="select mb-5"
        value={stage}
        onChange={(event) => setStage(event.target.value)}
      >
        <option value="all">All stages</option>
        <option value="not_applied">Not applied</option>
        <option value="applied">Applied</option>
        <option value="interview">Interview</option>
        <option value="closed">Closed</option>
      </select>
      {query.isPending && <output>Loading tracked jobs…</output>}
      {query.isError && <p role="alert">Tracked jobs could not be loaded.</p>}
      {query.data
        ?.filter((item) => stage === 'all' || item.stage === stage)
        .map((item) => (
          <article key={item.job_id} className="mb-5 rounded-box border border-base-300 p-5">
            <h2 className="text-lg font-semibold">{item.item.job.title}</h2>
            <p>{item.item.job.company}</p>
            <JobTracking jobId={item.job_id} />
          </article>
        ))}
    </>
  )
}
