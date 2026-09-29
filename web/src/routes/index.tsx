import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({ component: Home })

function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 sm:py-24">
      <p className="mb-6 text-sm font-semibold tracking-wide">JobScout</p>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        Find your next opportunity.
      </h1>
      <p className="mt-5 max-w-xl text-lg text-base-content/75">
        Discover roles that fit your background, skills, and goals.
      </p>
      <section className="card mt-10 bg-base-100 card-border" aria-labelledby="availability">
        <div className="card-body">
          <h2 id="availability" className="card-title">
            Job search is coming soon
          </h2>
          <p>We are building the search experience. Check back to start exploring opportunities.</p>
        </div>
      </section>
    </main>
  )
}
