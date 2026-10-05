import { Icon } from '../icon'
export function WorkflowSteps({ step }: { step: number }) {
  return (
    <ol
      aria-label="Job search steps"
      className="mb-7 grid grid-cols-3 rounded-box border border-base-300 bg-base-100 px-2 py-4 sm:px-5 lg:top-0 lg:min-h-20"
    >
      {['Tell us about yourself', 'Confirm your preferences', 'Explore opportunities'].map(
        (label, index) => (
          <li
            key={label}
            aria-current={(step === 3 ? 2 : Math.min(step, 2)) === index ? 'step' : undefined}
            className={`flex items-center justify-center gap-2 border-base-300 text-xs sm:justify-start sm:gap-3 sm:px-4 sm:text-sm ${index !== 2 ? 'border-r' : ''} ${step >= index ? 'font-medium text-base-content' : 'text-base-content/40'}`}
          >
            <span
              className={`flex size-8 shrink-0 items-center justify-center rounded-full text-[10px] leading-tight sm:size-7 ${step > index ? 'bg-primary/25 text-primary-content' : step === index ? 'bg-base-content text-base-100' : 'bg-base-200'}`}
            >
              {step > index ? <Icon name="check" size={13} /> : `0${index + 1}`}
            </span>
            {label}
          </li>
        ),
      )}
    </ol>
  )
}
