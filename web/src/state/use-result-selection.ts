import { useNavigate, useRouter, useSearch } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

import type { RecommendationItem } from '../lib/contracts'
import {
  nextJobAfterRemoval,
  selectionAfterFilter,
  visibleJobs,
  type ResultSearch,
} from '../lib/result-navigation'

export function useResultSelection(
  jobs: RecommendationItem[],
  savedOnly: boolean,
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void,
) {
  const navigate = useNavigate()
  const router = useRouter()
  const search = useSearch({ strict: false })
  const filtered = visibleJobs(jobs, search)
  const selected = filtered.find(({ job }) => job.job_id === search.job) ?? filtered[0]
  const detailOpen = Boolean(search.job && selected?.job.job_id === search.job)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  const detailHeading = useRef<HTMLHeadingElement>(null)
  const previousJob = useRef<string | undefined>(undefined)
  const listScroll = useRef(0)
  const openedFromList = useRef(false)
  const invalidSelection = Boolean(
    search.job && !filtered.some(({ job }) => job.job_id === search.job),
  )

  function changeSearch(next: ResultSearch, replace = true) {
    void navigate({ to: '.', search: next, replace, resetScroll: false })
  }
  useEffect(() => {
    if (invalidSelection)
      void navigate({
        to: '.',
        search: { ...search, job: undefined },
        replace: true,
        resetScroll: false,
      })
  }, [invalidSelection, navigate, savedOnly, search])

  useEffect(() => {
    if (!window.matchMedia('(min-width: 1100px)').matches) {
      if (detailOpen) {
        detailHeading.current?.focus()
        window.scrollTo(0, 0)
      } else if (previousJob.current) {
        buttons.current.get(previousJob.current)?.focus({ preventScroll: true })
        window.scrollTo(0, listScroll.current)
      }
    }
    previousJob.current = detailOpen ? search.job : undefined
  }, [detailOpen, search.job])

  function filterTo(next: ResultSearch) {
    const nextSelected = selectionAfterFilter(jobs, selected?.job.job_id, visibleJobs(jobs, next))
    const showDetail = detailOpen || window.matchMedia('(min-width: 1100px)').matches
    changeSearch({ ...next, job: showDetail ? nextSelected : undefined })
  }
  function selectJob(id: string) {
    if (!detailOpen) {
      listScroll.current = window.scrollY
      openedFromList.current = true
    }
    changeSearch({ ...search, job: id }, detailOpen)
  }
  function back() {
    if (openedFromList.current) {
      openedFromList.current = false
      router.history.back()
    } else changeSearch({ ...search, job: undefined })
  }
  async function toggle(item: RecommendationItem) {
    const location = router.state.location.href
    const removed = await onToggle(item)
    if (removed === false || router.state.location.href !== location) return
    if (savedOnly && item.job.job_id === selected?.job.job_id)
      changeSearch({
        ...search,
        job: detailOpen ? nextJobAfterRemoval(filtered, item.job.job_id) : undefined,
      })
  }
  return {
    search,
    filtered,
    selected,
    detailOpen,
    buttons,
    detailHeading,
    changeSearch,
    filterTo,
    selectJob,
    back,
    toggle,
  }
}
