import type { ScoutInput } from './contracts'

export type ProfileFormValues = Omit<ScoutInput, 'target_directions'> & { directions: string }

export function createProfileDraft(): ProfileFormValues {
  return {
    description: '',
    resume: null,
    directions: '',
    preferences: {
      location: '',
      location_unrestricted: false,
      employment_type: null,
      salary_range: null,
      work_mode: null,
      industry: null,
    },
  }
}

export function createExampleDraft(): ProfileFormValues {
  return {
    description:
      '我是计算机专业应届毕业生，熟悉 React、TypeScript 和 Python，做过校园活动网站与数据分析项目。希望找到能参与真实产品、与团队一起成长的初级岗位。',
    resume: null,
    directions: '前端开发，数据分析',
    preferences: {
      location: '香港',
      location_unrestricted: false,
      employment_type: 'full-time',
      salary_range: 'HK$ 20,000–28,000 / 月',
      work_mode: null,
      industry: null,
    },
  }
}

export function parseDirections(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[,，、]/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ]
}

export function toScoutInput({ directions, ...values }: ProfileFormValues): ScoutInput {
  const { preferences } = values
  return {
    ...values,
    description: values.description.trim(),
    target_directions: parseDirections(directions),
    preferences: {
      ...preferences,
      location: preferences.location_unrestricted ? null : preferences.location?.trim() || null,
      employment_type: preferences.employment_type || null,
      salary_range: preferences.salary_range?.trim() || null,
      work_mode: preferences.work_mode || null,
    },
  }
}
