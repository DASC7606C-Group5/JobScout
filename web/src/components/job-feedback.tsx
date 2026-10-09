import type { ResultReaction } from '../lib/contracts'
import { Icon } from './icon'

export function JobFeedback({
  onChange,
  reaction,
  hidden,
  disabled,
}: {
  onChange: (reaction: ResultReaction | null) => unknown
  reaction: ResultReaction | undefined
  hidden: boolean
  disabled: boolean
}) {
  return (
    <div className="ml-auto flex items-center gap-1" aria-label="Job feedback">
      <button
        type="button"
        className={`btn btn-sm ${reaction === 'interested' ? 'border-secondary-content/20 bg-secondary/35 text-secondary-content' : 'btn-ghost'}`}
        aria-pressed={reaction === 'interested'}
        disabled={disabled}
        onClick={() => onChange(reaction === 'interested' ? null : 'interested')}
      >
        <Icon name="heart" size={16} className={reaction === 'interested' ? 'fill-current' : ''} />{' '}
        Interested
      </button>
      {(!hidden || reaction === 'not_interested') && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled}
          onClick={() => onChange(hidden ? null : 'not_interested')}
        >
          <Icon name={hidden ? 'check' : 'hidden'} size={16} /> {hidden ? 'Show job' : 'Not for me'}
        </button>
      )}
    </div>
  )
}

export function HiddenJobNotice({
  reaction,
  exclusions,
}: {
  reaction: ResultReaction | undefined
  exclusions: string[]
}) {
  return (
    <div className="rounded-box bg-base-200/60 p-3 text-sm">
      <p className="font-medium">Hidden from your results</p>
      {reaction === 'not_interested' && (
        <p className="mt-1 text-base-content/70">You marked this job as not for you.</p>
      )}
      {exclusions.length > 0 && (
        <>
          <p className="mt-1 text-base-content/70">Matches your excluded preferences:</p>
          <ul className="mt-1 list-disc pl-4">
            {exclusions.map((description) => (
              <li key={description}>{description}</li>
            ))}
          </ul>
          <p className="mt-2 text-base-content/70">
            Ask in the conversation to change these preferences before this job can appear again.
          </p>
        </>
      )}
    </div>
  )
}
