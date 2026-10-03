import { Icon } from './icon'

export function JourneyAside() {
  return (
    <aside className="space-y-5">
      <section className="overflow-hidden rounded-2xl border border-secondary/55 bg-secondary/20">
        <div
          className="relative flex h-48 items-center justify-center overflow-hidden"
          aria-hidden="true"
        >
          <div className="absolute size-36 rounded-full border border-secondary/65" />
          <div className="absolute size-48 rounded-full border border-secondary/40" />
          <div className="absolute top-7 right-10 text-secondary-content/55">
            <Icon name="sparkles" size={21} />
          </div>
          <div className="absolute bottom-8 left-10 size-3 rounded-full bg-accent" />
          <div className="relative flex h-28 w-24 -rotate-12 flex-col gap-2 rounded-2xl border border-base-300 bg-base-100 p-4 shadow-sm">
            <div className="flex size-9 items-center justify-center rounded-full bg-secondary/60">
              <Icon name="briefcase" size={19} />
            </div>
            <div className="mt-1 h-1.5 w-12 rounded-full bg-base-content/20" />
            <div className="h-1.5 w-9 rounded-full bg-base-content/10" />
          </div>
          <div className="relative -ml-4 flex size-22 rotate-12 items-center justify-center rounded-2xl border-4 border-base-100 bg-primary/65 text-primary-content shadow-sm">
            <Icon name="compass" size={49} />
          </div>
          <div className="absolute right-13 bottom-7 flex size-7 items-center justify-center rounded-full bg-accent text-accent-content">
            <Icon name="check" size={15} />
          </div>
        </div>
        <div className="px-6 pb-6">
          <p className="mb-2 text-[10px] font-bold tracking-[0.18em] text-secondary-content/70">
            A LITTLE GUIDANCE, A NEW BEGINNING
          </p>
          <h2 className="text-xl leading-relaxed font-semibold">
            下一站，
            <br />
            更适合你的地方。
          </h2>
          <p className="mt-3 text-xs leading-6 text-base-content/65">
            从你的经历出发，逐步明确方向，
            <br className="hidden xl:block" />
            让每一次投递都多一分准备。
          </p>
        </div>
      </section>
      <p className="flex items-start gap-2 px-2 text-xs leading-5 text-base-content/50">
        <Icon name="footsteps" size={17} className="mt-0.5 shrink-0" />
        每个人都有自己的节奏。
        <br />
        先迈出一小步，也很好。
      </p>
    </aside>
  )
}
