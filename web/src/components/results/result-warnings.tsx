const FALLBACK_WARNING_MARKER = 'a deterministic fallback was used.'
const MERGED_JOB_WARNING_MARKER = 'no responsibilities or required skills extracted.'

type WarningGroup = {
  label: string
  warnings: string[]
}

function WarningGroup({ label, warnings }: WarningGroup) {
  if (!warnings.length) return null
  return (
    <details className="collapse-arrow collapse mb-5 rounded-xl border border-base-300 bg-base-100 text-left text-xs leading-6 text-base-content/70">
      <summary className="collapse-title text-sm font-medium">
        {label} ({warnings.length})
      </summary>
      <div className="collapse-content space-y-2">
        {warnings.map((warning) => (
          <p key={warning} className="break-words">
            {warning}
          </p>
        ))}
      </div>
    </details>
  )
}

export function ResultWarnings({ warnings }: { warnings: string[] }) {
  const fallbackWarnings: string[] = []
  const mergedJobWarnings: string[] = []
  const jobQualityWarnings: string[] = []
  const preferenceWarnings: string[] = []
  const sourceWarnings: string[] = []
  const otherWarnings: string[] = []

  for (const warning of new Set(warnings)) {
    if (warning.includes(FALLBACK_WARNING_MARKER)) {
      fallbackWarnings.push(warning)
    } else if (warning.includes(MERGED_JOB_WARNING_MARKER)) {
      mergedJobWarnings.push(warning)
    } else if (warning.startsWith('Job ')) {
      jobQualityWarnings.push(warning)
    } else if (warning.startsWith('Could not reliably verify ')) {
      preferenceWarnings.push(warning)
    } else if (warning.includes('/') && warning.includes(':')) {
      sourceWarnings.push(warning)
    } else {
      otherWarnings.push(warning)
    }
  }

  return (
    <>
      <WarningGroup label="Model analysis fallback" warnings={fallbackWarnings} />
      <WarningGroup label="Missing job description fields" warnings={mergedJobWarnings} />
      <WarningGroup label="Job evidence and status" warnings={jobQualityWarnings} />
      <WarningGroup label="Preference checks" warnings={preferenceWarnings} />
      <WarningGroup label="Source search and coverage" warnings={sourceWarnings} />
      <WarningGroup label="Other notices" warnings={otherWarnings} />
    </>
  )
}
