const FALLBACK_WARNING_MARKER = '模型分析不可用或证据未通过核验；已使用确定性保守回退。'
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
        {label}（{warnings.length} 条）
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
    } else if (warning.startsWith('岗位 ')) {
      jobQualityWarnings.push(warning)
    } else if (warning.startsWith('无法可靠验证 ')) {
      preferenceWarnings.push(warning)
    } else if (warning.includes('/') && warning.includes(':')) {
      sourceWarnings.push(warning)
    } else {
      otherWarnings.push(warning)
    }
  }

  return (
    <>
      <WarningGroup label="模型分析回退" warnings={fallbackWarnings} />
      <WarningGroup label="岗位描述字段缺失" warnings={mergedJobWarnings} />
      <WarningGroup label="岗位证据与时效提示" warnings={jobQualityWarnings} />
      <WarningGroup label="偏好核验提示" warnings={preferenceWarnings} />
      <WarningGroup label="来源检索与覆盖提示" warnings={sourceWarnings} />
      <WarningGroup label="其他提示" warnings={otherWarnings} />
    </>
  )
}
