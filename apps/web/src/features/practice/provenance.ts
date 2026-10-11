import type { BookDetail, Language, StudyPlan } from '../../api/practice';
import type { Labels } from '../../i18n';

export function textbookVersionLabel(book: BookDetail, plan: StudyPlan, labels: Labels, language: Language): string {
  const course = book.courses.find((item) => item.course_id === plan.course_id && item.content_version_id === plan.content_version_id);
  const parts = [book.edition || book.publisher];
  parts.push(course?.content_version_sequence ? `${labels.contentRevision} ${course.content_version_sequence}` : labels.currentPublication);
  if (course?.content_version_published_at) {
    const date = new Date(course.content_version_published_at);
    if (!Number.isNaN(date.getTime())) {
      parts.push(new Intl.DateTimeFormat(language === 'en' ? 'en' : 'zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }).format(date));
    }
  }
  return parts.join(' · ');
}
