import { requestHeaders } from '../api';

export type Language = 'zh' | 'en' | 'bilingual';
export type QuestionType = 'multiple_choice' | 'true_false' | 'fill_in_the_blank' | 'short_answer';
export type Difficulty = 'introductory' | 'standard' | 'challenge';

export interface Category {
  id: string;
  stable_key: string;
  display_name: string;
  category_type: 'education_level' | 'subject' | 'publisher' | 'grade';
  parent_id: string | null;
  book_count: number;
}

export interface Book {
  id: string;
  title: string;
  education_level: string;
  subject: string;
  grade: string;
  publisher: string;
  series: string;
  edition: string | null;
  term: string;
  language: string;
  cover_uri: string | null;
  lifecycle_status: 'draft' | 'published' | 'archived';
}

export interface BookCourse {
  course_id: string;
  course_run_id: string;
  code: string;
  name: string;
  content_version_id: string;
}

export interface BookDetail extends Book { courses: BookCourse[] }
export interface BookPage { items: Book[]; next_cursor: string | null }
export interface SearchFilters {
  q?: string;
  education_level?: string;
  grade?: string;
  subject?: string;
  publisher?: string;
  edition?: string;
  term?: string;
  language?: string;
  cursor?: string;
}

export interface StudyModule { id: string; ordinal: number; title: string; objectives: string[] }
export interface StudyPlan {
  id: string;
  book_id: string;
  course_id: string;
  content_version_id: string;
  name: string;
  modules: StudyModule[];
}

export type GenerationStatus = 'queued' | 'retrieving' | 'generating' | 'validating' | 'ready' | 'failed' | 'cancelled';
export interface Generation {
  id: string;
  book_id: string;
  course_id: string;
  status: GenerationStatus;
  practice_set_id: string | null;
  error_code: string | null;
  retryable: boolean | null;
}

interface ExerciseBase {
  id: string;
  ordinal: number;
  prompt: string;
  difficulty: Difficulty;
  language: Language;
  evidence_citation_ids: string[];
}
export type Exercise = ExerciseBase & (
  | { type: 'multiple_choice'; options: { id: string; text: string }[] }
  | { type: 'true_false' }
  | { type: 'fill_in_the_blank' }
  | { type: 'short_answer'; rubric: { description: string; weight: number }[] }
);
export interface PracticeSet {
  id: string;
  book_id: string;
  course_id: string;
  content_version_id: string;
  study_plan_id: string;
  exercises: Exercise[];
}
export interface AnswerRelease {
  answer: string | boolean | string[];
  rationale: string;
  evidence_citation_ids: string[];
}
export interface Feedback {
  id: string;
  exercise_id: string;
  attempt_number: number;
  outcome: 'correct' | 'incorrect' | 'provisional' | 'gave_up';
  correct: boolean | null;
  score: number | null;
  hint: string | null;
  released_answer: AnswerRelease | null;
}
export interface SetProgress {
  practice_set_id: string;
  book_id: string;
  status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED';
  total_questions: number;
  completed_questions: number;
  attempted_questions: number;
  correct_questions: number;
  next_exercise_id: string | null;
}
export interface StudyStatus { sets: SetProgress[]; plans: object[] }
export interface Resume {
  practice_set_id: string;
  book_id: string;
  course_id: string;
  exercise_id: string;
  attempt_number: number;
  released: boolean;
}

const base = '/v1/practice';

export class PracticeApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, options: RequestInit = {}, key?: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: {
      ...requestHeaders({ ...(options.body ? { 'Content-Type': 'application/json' } : {}) }),
      ...(key ? { 'Idempotency-Key': key } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new PracticeApiError(response.status, typeof error?.detail === 'string' ? error.detail : `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const bookPath = (bookId: string) => `/catalog/books/${encodeURIComponent(bookId)}`;
const setPath = (setId: string) => `/sets/${encodeURIComponent(setId)}`;

export const practiceApi = {
  categories: () => request<Category[]>('/catalog/categories'),
  books: (filters: SearchFilters) => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
    return request<BookPage>(`/catalog/books?${query}`);
  },
  book: (id: string) => request<BookDetail>(bookPath(id)),
  courses: (id: string) => request<BookCourse[]>(`${bookPath(id)}/courses`),
  plan: (id: string) => request<StudyPlan>(`${bookPath(id)}/study-plan`),
  generate: (id: string, body: { count: number; module_id?: string; language: Language; difficulty: Difficulty; question_types: QuestionType[] }, key: string) =>
    request<Generation>(`${bookPath(id)}/generations`, { method: 'POST', body: JSON.stringify(body) }, key),
  generation: (id: string) => request<Generation>(`/generations/${encodeURIComponent(id)}`),
  cancelGeneration: (id: string) => request<Generation>(`/generations/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  set: (id: string) => request<PracticeSet>(setPath(id)),
  submit: (setId: string, exerciseId: string, answer: string | boolean, key: string) =>
    request<Feedback>(`${setPath(setId)}/exercises/${encodeURIComponent(exerciseId)}/attempts`, { method: 'POST', body: JSON.stringify({ answer }) }, key),
  giveUp: (setId: string, exerciseId: string, key: string) =>
    request<Feedback>(`${setPath(setId)}/exercises/${encodeURIComponent(exerciseId)}/give-up`, { method: 'POST' }, key),
  status: () => request<StudyStatus>('/study-status'),
  resume: () => request<Resume | null>('/resume'),
  clearResume: (key: string) => request<void>('/resume', { method: 'DELETE' }, key),
  report: (exerciseId: string, reason: 'incorrect' | 'ambiguous' | 'unsafe', detail: string) =>
    request<void>(`/exercises/${encodeURIComponent(exerciseId)}/reports`, { method: 'POST', body: JSON.stringify({ reason, detail }) }),
};
