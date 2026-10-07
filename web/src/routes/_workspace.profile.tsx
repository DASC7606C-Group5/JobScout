import { createFileRoute } from '@tanstack/react-router'

import { PersonalProfileEditor } from '../components/career/profile-editor'
import { PageHeading } from '../components/layout/page-heading'

export const Route = createFileRoute('/_workspace/profile')({ component: ProfilePage })
function ProfilePage() {
  return (
    <>
      <PageHeading
        eyebrow="PERSONAL PROFILE"
        title="Your current background"
        description="Save your experience and evidence for your job-search tasks."
      />
      <PersonalProfileEditor />
    </>
  )
}
