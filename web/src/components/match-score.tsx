import { dimensionLabels, type MatchScore } from '../lib/matching-contracts'

export function MatchScoreBadge({ score }: { score: MatchScore | null }) {
  if (!score) return null
  return (
    <span className="badge h-auto badge-outline py-1">
      {score.total === null ? 'Match unknown' : `Match ${score.total}/100`}
      {score.provisional && ' · Provisional'} · {score.coverage}% assessed
    </span>
  )
}

function coordinate(axis: number, score: number) {
  const angle = (axis * Math.PI) / 3 - Math.PI / 2
  return { x: 160 + Math.cos(angle) * score, y: 145 + Math.sin(angle) * score }
}

export function MatchScoreDetail({ score }: { score: MatchScore | null }) {
  if (!score) return null
  const points = score.dimensions.map((dimension, index) =>
    dimension.status === 'assessed' && dimension.score !== null
      ? coordinate(index, dimension.score)
      : null,
  )
  return (
    <section aria-label="Six-dimension match">
      <h3 className="mb-2 font-semibold">Match to your background and preferences</h3>
      <MatchScoreBadge score={score} />
      <p className="mt-2 text-base-content/70">
        Based on {score.assessed_weight} of {score.applicable_weight} applicable weight.
        {score.provisional && ' Missing evidence makes this score provisional.'}
        {' Unknown dimensions are not zero. This is not a hiring probability.'}
      </p>
      <svg viewBox="0 0 320 290" className="mx-auto w-full max-w-sm" aria-hidden="true">
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
            className="text-base-content/20"
          />
        ))}
        {score.dimensions.map((dimension, axis) => {
          const edge = coordinate(axis, 100)
          const label = coordinate(axis, 120)
          const point = points[axis]
          const next = points[(axis + 1) % 6]
          return (
            <g key={dimension.id}>
              <line
                x1={160}
                y1={145}
                x2={edge.x}
                y2={edge.y}
                stroke="currentColor"
                className="text-base-content/20"
              />
              <text
                x={label.x}
                y={label.y}
                textAnchor="middle"
                className="fill-base-content text-[10px]"
              >
                {dimensionLabels[dimension.id]}
              </text>
              {point && next && (
                <line
                  x1={point.x}
                  y1={point.y}
                  x2={next.x}
                  y2={next.y}
                  stroke="currentColor"
                  className="text-info"
                  strokeWidth={2}
                />
              )}
              {point && <circle cx={point.x} cy={point.y} r={4} className="fill-info" />}
            </g>
          )
        })}
      </svg>
      <div className="overflow-x-auto">
        <table className="table table-sm">
          <caption className="text-left font-semibold">Dimension scores and evidence</caption>
          <thead>
            <tr>
              <th scope="col">Dimension</th>
              <th scope="col">Score</th>
              <th scope="col">Evidence and gaps</th>
            </tr>
          </thead>
          <tbody>
            {score.dimensions.map((dimension) => (
              <tr key={dimension.id}>
                <th scope="row" aria-label={dimensionLabels[dimension.id]}>
                  {dimensionLabels[dimension.id]} ({dimension.weight}%)
                </th>
                <td>
                  {dimension.score === null
                    ? dimension.status === 'not_applicable'
                      ? 'Not applicable'
                      : 'Unknown'
                    : `${dimension.score}/100`}
                </td>
                <td>
                  <details
                    aria-label={`${dimensionLabels[dimension.id]} evidence`}
                    className="collapse-arrow collapse border border-base-300"
                  >
                    <summary className="collapse-title p-3 pr-8">
                      {dimension.explanation || 'More information needed'}
                    </summary>
                    <div className="collapse-content">
                      <p className="font-semibold">Job requirement</p>
                      {dimension.job_source_quotes.map((quote) => (
                        <blockquote key={`${quote.document_id}:${quote.excerpt}`}>
                          {quote.excerpt}
                        </blockquote>
                      ))}
                      <p className="mt-2 font-semibold">Applicant evidence</p>
                      {dimension.profile_source_quotes.map((quote) => (
                        <blockquote key={`${quote.document_id}:${quote.excerpt}`}>
                          {quote.excerpt}
                        </blockquote>
                      ))}
                      <p className="mt-2 font-semibold">Gap or unknown</p>
                      {dimension.missing_information.map((text) => (
                        <p key={text}>{text}</p>
                      ))}
                    </div>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
