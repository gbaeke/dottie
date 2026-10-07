import type { DottieIn, SkillOut, TemplateOut } from '@/client/types.gen'

/** A template as a creation request: skills are named in the template and numbered in the database. */
export function fromTemplate(t: TemplateOut, skills: SkillOut[]): DottieIn {
  return {
    name: t.name,
    role: t.role,
    hue: t.hue,
    personality: t.personality,
    tools: t.tools,
    skill_ids: skills.filter((s) => t.skills.includes(s.name)).map((s) => s.id),
  }
}
