import { useEffect, useId, useRef, useState } from 'react'

import {
  dimensionLabels,
  type DimensionId,
  type MatchDimension,
  type MatchScore,
} from '../lib/matching-contracts'

export function MatchScoreValue({
  score,
  prominent = false,
}: {
  score: MatchScore
  prominent?: boolean
}) {
  if (score.total === null)
    return <span className="text-xs text-base-content/65">Match not yet available</span>
  return (
    <span className="inline-flex items-baseline gap-1.5 text-xs text-base-content/65">
      Match
      <span className="tabular-nums">
        <strong className={`font-semibold text-base-content ${prominent ? 'text-2xl' : ''}`}>
          {score.total}
        </strong>
        /100
      </span>
    </span>
  )
}

export function MatchScoreSummary({ score }: { score: MatchScore | null }) {
  if (!score) return null
  return (
    <span className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-base-300/65 pt-3">
      <MatchScoreValue score={score} />
      {score.provisional && score.total !== null && (
        <span className="text-xs text-base-content/65">Limited information</span>
      )}
    </span>
  )
}

const labelPositions: Record<DimensionId, string> = {
  skills: 'top-0 left-1/2 -translate-x-1/2 tooltip-bottom',
  responsibilities: 'top-14 right-0 tooltip-bottom tooltip-end',
  experience: 'right-0 bottom-12 tooltip-top tooltip-end',
  seniority: 'bottom-0 left-1/2 -translate-x-1/2 tooltip-top',
  education: 'bottom-12 left-0 tooltip-top tooltip-start',
  preferences: 'top-14 left-0 tooltip-bottom tooltip-start',
}

function coordinate(axis: number, score: number) {
  const angle = (axis * Math.PI) / 3 - Math.PI / 2
  const radius = (score / 100) * 86
  return { x: 100 + Math.cos(angle) * radius, y: 100 + Math.sin(angle) * radius }
}

function dimensionValue(dimension: MatchDimension) {
  if (dimension.score !== null) return `${dimension.score}/100`
  return dimension.status === 'not_applicable' ? 'Not applicable' : 'Not enough information'
}

function DimensionLabel({
  dimension,
  open,
  onOpen,
  onHover,
  onDismiss,
}: {
  dimension: MatchDimension
  open: boolean
  onOpen: () => void
  onHover: () => void
  onDismiss: () => void
}) {
  const tooltipId = useId()
  const explanation = dimension.explanation.trim()
  const missing = dimension.missing_information.filter((text) => !explanation.includes(text))
  return (
    <div
      className={`tooltip absolute ${labelPositions[dimension.id]} ${open ? 'z-20 tooltip-open' : '[&::after]:hidden [&>.tooltip-content]:invisible [&>.tooltip-content]:opacity-0'}`}
      onMouseEnter={onHover}
    >
      <button
        type="button"
        className="btn h-auto min-h-11 flex-col gap-0 rounded-sm border-0 btn-ghost px-1 py-1 text-xs leading-4 font-normal"
        aria-label={`${dimensionLabels[dimension.id]}: ${dimensionValue(dimension)}`}
        aria-describedby={tooltipId}
        onFocus={onOpen}
        onBlur={onDismiss}
        onClick={onOpen}
      >
        <span className="text-base-content/65">{dimensionLabels[dimension.id]}</span>
        <span className="font-medium tabular-nums">
          {dimension.score ?? (dimension.status === 'not_applicable' ? 'N/A' : '—')}
        </span>
      </button>
      <div
        id={tooltipId}
        role="tooltip"
        className="tooltip-content pointer-events-auto w-64 max-w-[calc(100vw-6rem)] space-y-2 rounded-xl p-3 text-left text-xs leading-5"
      >
        <p className="font-semibold">
          {dimensionLabels[dimension.id]} · {dimensionValue(dimension)}
        </p>
        {explanation && <p>{explanation}</p>}
        {missing.map((text) => (
          <p key={text}>{text}</p>
        ))}
        {!explanation && !missing.length && (
          <p>
            {dimension.status === 'not_applicable'
              ? 'This area does not apply to the job requirements.'
              : 'More detail from your profile or the job listing is needed to compare this area.'}
          </p>
        )}
      </div>
    </div>
  )
}

export function MatchRadar({ score }: { score: MatchScore }) {
  const [activeDimension, setActiveDimension] = useState<DimensionId | null>(null)
  const hoverDismissed = useRef(false)
  useEffect(() => {
    if (activeDimension === null) return
    const dismiss = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      hoverDismissed.current = true
      setActiveDimension(null)
      event.stopPropagation()
    }
    document.addEventListener('keydown', dismiss, true)
    return () => document.removeEventListener('keydown', dismiss, true)
  }, [activeDimension])
  const assessed = score.dimensions.filter((dimension) => dimension.status === 'assessed')
  const applicable = score.dimensions.filter((dimension) => dimension.status !== 'not_applicable')
  const hasUnknown = score.dimensions.some((dimension) => dimension.status === 'unknown')
  const hasNotApplicable = applicable.length < score.dimensions.length
  const completeShape = assessed.length === score.dimensions.length
  const points = score.dimensions.map((dimension, index) =>
    dimension.status === 'assessed' && dimension.score !== null
      ? coordinate(index, dimension.score)
      : null,
  )

  return (
    <figure
      aria-label="Six-dimension match scores out of 100"
      className="mx-auto block w-full max-w-72 overflow-visible"
    >
      <div
        className="relative h-69"
        onMouseLeave={(event) => {
          hoverDismissed.current = false
          if (!event.currentTarget.contains(document.activeElement)) setActiveDimension(null)
        }}
      >
        <svg
          viewBox="0 0 200 200"
          className="absolute top-13 left-1/2 h-44 w-44 -translate-x-1/2 text-base-content/55"
          aria-hidden="true"
        >
          {[25, 50, 75, 100].map((radius) => (
            <polygon
              key={radius}
              points={score.dimensions
                .map((_, axis) => {
                  const point = coordinate(axis, radius)
                  return `${point.x},${point.y}`
                })
                .join(' ')}
              fill="none"
              stroke="currentColor"
              className="text-base-content/15"
            />
          ))}
          {score.dimensions.map((dimension, axis) => {
            const edge = coordinate(axis, 100)
            return (
              <line
                key={dimension.id}
                x1={100}
                y1={100}
                x2={edge.x}
                y2={edge.y}
                stroke="currentColor"
                className="text-base-content/15"
              />
            )
          })}
          {completeShape && (
            <polygon
              data-match-area="assessed"
              points={points.map((point) => `${point!.x},${point!.y}`).join(' ')}
              stroke="currentColor"
              strokeWidth={2}
              strokeLinejoin="round"
              className="fill-current/10"
            />
          )}
          {score.dimensions.map((dimension, axis) => {
            const point = points[axis]
            if (!point) return null
            return (
              <g
                key={dimension.id}
                onMouseEnter={() => {
                  if (!hoverDismissed.current) setActiveDimension(dimension.id)
                }}
              >
                {!completeShape && (
                  <line
                    x1={100}
                    y1={100}
                    x2={point.x}
                    y2={point.y}
                    stroke="currentColor"
                    strokeWidth={2}
                  />
                )}
                <circle cx={point.x} cy={point.y} r={12} fill="transparent" />
                <circle
                  data-dimension={dimension.id}
                  cx={point.x}
                  cy={point.y}
                  r={3.5}
                  fill="currentColor"
                />
              </g>
            )
          })}
        </svg>
        {score.dimensions.map((dimension) => (
          <DimensionLabel
            key={dimension.id}
            dimension={dimension}
            open={activeDimension === dimension.id}
            onOpen={() => {
              hoverDismissed.current = false
              setActiveDimension(dimension.id)
            }}
            onHover={() => {
              if (!hoverDismissed.current) setActiveDimension(dimension.id)
            }}
            onDismiss={() => {
              hoverDismissed.current = true
              setActiveDimension(null)
            }}
          />
        ))}
      </div>
      <figcaption className="mt-2 space-y-1 text-center text-xs leading-5 text-base-content/65">
        <p>
          {assessed.length} of {applicable.length} {hasNotApplicable ? 'applicable ' : ''}areas
          assessed · Scores out of 100
        </p>
        {(hasUnknown || hasNotApplicable) && (
          <p>
            {[hasUnknown && '— More information needed', hasNotApplicable && 'N/A Not applicable']
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
      </figcaption>
    </figure>
  )
}
