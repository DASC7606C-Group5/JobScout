import { useId, useState } from 'react'

import type {
  ApplicationStage,
  FeedbackWrite,
  JobApplication,
  TaskJobFeedback,
} from '../../lib/career-contracts'
import {
  useApplications,
  useSaveApplication,
  useSaveFeedback,
  useTaskFeedback,
} from '../../state/career-queries'

export function JobTracking({
  jobId,
  sessionId,
}: {
  jobId: string
  sessionId?: string | undefined
}) {
  const applications = useApplications()
  const feedback = useTaskFeedback(sessionId)
  if (applications.isPending || (sessionId && feedback.isPending))
    return <output>Loading job tracking…</output>
  if (applications.isError || (sessionId && feedback.isError))
    return <p role="alert">Job tracking could not be loaded.</p>
  const application = applications.data?.find((item) => item.job_id === jobId)
  const interest = feedback.data?.find((item) => item.job_id === jobId)
  return (
    <section aria-label="Job tracking" className="space-y-4">
      {sessionId && (
        <InterestEditor
          key={interest?.updated_at ?? 'new'}
          sessionId={sessionId}
          jobId={jobId}
          current={interest}
        />
      )}
      <ApplicationEditor
        key={application?.updated_at ?? 'new'}
        jobId={jobId}
        sessionId={sessionId}
        current={application}
      />
    </section>
  )
}

function InterestEditor({
  sessionId,
  jobId,
  current,
}: {
  sessionId: string
  jobId: string
  current?: TaskJobFeedback | undefined
}) {
  const id = useId()
  const [value, setValue] = useState<FeedbackWrite>(
    current ?? { interest: 'neutral', reason: '', scope: 'job' },
  )
  const save = useSaveFeedback(sessionId, jobId)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate(value)
      }}
    >
      <fieldset className="fieldset" disabled={save.isPending}>
        <legend className="fieldset-legend">Interest in this task</legend>
        <label className="label" htmlFor={id + '-job-interest'}>
          Interest
        </label>
        <select
          id={id + '-job-interest'}
          className="select w-full"
          value={value.interest}
          onChange={(event) =>
            setValue({ ...value, interest: event.target.value as FeedbackWrite['interest'] })
          }
        >
          <option value="neutral">Neutral</option>
          <option value="interested">Interested</option>
          <option value="not_interested">Not interested</option>
        </select>
        <label className="label" htmlFor={id + '-interest-reason'}>
          Reason
        </label>
        <textarea
          id={id + '-interest-reason'}
          className="textarea w-full"
          value={value.reason}
          onChange={(event) => setValue({ ...value, reason: event.target.value })}
        />
        <label className="label" htmlFor={id + '-interest-scope'}>
          Apply reason to
        </label>
        <select
          id={id + '-interest-scope'}
          className="select w-full"
          value={value.scope}
          onChange={(event) =>
            setValue({ ...value, scope: event.target.value as FeedbackWrite['scope'] })
          }
        >
          <option value="job">This job only</option>
          <option value="task">Soft preferences for this task</option>
        </select>
        <p>
          Task feedback adjusts preferences. It does not change your skills or impose a hard
          exclusion.
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-sm" type="submit">
            Save interest
          </button>
          <button
            className="btn btn-sm"
            type="button"
            onClick={() => save.mutate({ interest: 'neutral', reason: '', scope: 'job' })}
          >
            Clear interest
          </button>
        </div>
        {save.isError && <p role="alert">Interest could not be saved.</p>}
      </fieldset>
    </form>
  )
}

function ApplicationEditor({
  jobId,
  sessionId,
  current,
}: {
  jobId: string
  sessionId?: string | undefined
  current?: JobApplication | undefined
}) {
  const id = useId()
  const [stage, setStage] = useState<ApplicationStage>(current?.stage ?? 'not_applied')
  const [note, setNote] = useState(current?.note ?? '')
  const save = useSaveApplication(jobId)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate({ stage, note, ...(sessionId ? { session_id: sessionId } : {}) })
      }}
    >
      <fieldset className="fieldset" disabled={save.isPending}>
        <legend className="fieldset-legend">Application progress · shared across tasks</legend>
        <label className="label" htmlFor={id + '-application-stage'}>
          Stage
        </label>
        <select
          id={id + '-application-stage'}
          className="select w-full"
          value={stage}
          onChange={(event) => setStage(event.target.value as ApplicationStage)}
        >
          <option value="not_applied">Not applied</option>
          <option value="applied">Applied</option>
          <option value="interview">Interview</option>
          <option value="closed">Closed</option>
        </select>
        <label className="label" htmlFor={id + '-application-note'}>
          Note
        </label>
        <textarea
          id={id + '-application-note'}
          className="textarea w-full"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <button className="btn btn-sm" type="submit">
          Save progress
        </button>
        {save.isError && <p role="alert">Progress could not be saved.</p>}
        {current?.history.map((entry, index) => (
          <p key={`${entry.changed_at}-${index}`}>
            {entry.stage.replaceAll('_', ' ')} · {new Date(entry.changed_at).toLocaleString()}{' '}
            {entry.note}
          </p>
        ))}
      </fieldset>
    </form>
  )
}
