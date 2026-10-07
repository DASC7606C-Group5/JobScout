import { Icon } from '../icon'
export function WorkflowSteps({ step }: { step: number }) {
  return (
    <ol
      aria-label="Job search steps"
      className="mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"
    >
      {['Your background', 'Review criteria', 'Explore jobs'].map((label, index) => (
        <li
          key={label}
          aria-current={(step === 3 ? 2 : Math.min(step, 2)) === index ? 'step' : undefined}
          className={`flex items-center gap-2 text-xs ${step >= index ? 'font-medium text-base-content' : 'text-base-content/55'}`}
        >
          <span
            className={`flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] leading-tight ${step > index ? 'bg-primary/25 text-primary-content' : step === index ? 'bg-base-content text-base-100' : 'bg-base-200'}`}
          >
            {step > index ? <Icon name="check" size={13} /> : `0${index + 1}`}
          </span>
          {label}
        </li>
      ))}
    </ol>
  )
}
