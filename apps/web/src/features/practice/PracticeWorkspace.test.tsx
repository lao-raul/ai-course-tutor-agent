import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { AnswerInput, EvidenceSources } from './PracticeWorkspace';
import { textbookVersionLabel } from './provenance';
import type { BookDetail, Exercise, StudyPlan } from '../../api/practice';
import { getLabels } from '../../i18n';

const base = { id: 'exercise-1', ordinal: 0, prompt: 'What is 2 + 2?', difficulty: 'standard' as const, language: 'en' as const, evidence_citation_ids: ['chunk-1'] };

describe('safe answer input', () => {
  it('shows only question and options for multiple choice', () => {
    const exercise: Exercise = { ...base, type: 'multiple_choice', options: [{ id: 'A', text: 'Three' }, { id: 'B', text: 'Four' }] };
    const html = renderToStaticMarkup(<AnswerInput exercise={exercise} answer="" onChange={() => undefined} disabled={false} labels={getLabels('en')} />);
    expect(html).toContain('Three');
    expect(html).toContain('Four');
    expect(html).not.toContain('correct_option_id');
  });
  it('disables response control after completion', () => {
    const exercise: Exercise = { ...base, type: 'fill_in_the_blank' };
    expect(renderToStaticMarkup(<AnswerInput exercise={exercise} answer="" onChange={() => undefined} disabled labels={getLabels('zh')} />)).toContain('disabled=""');
  });
});

describe('human-readable textbook provenance', () => {
  it('shows edition, published revision and date instead of version UUID', () => {
    const book: BookDetail = {
      id: 'book', title: '三年级英语上册', education_level: 'primary', subject: '英语', grade: '3',
      publisher: '外研社', series: '三年级起点', edition: '外研社版', term: '上册', language: 'zh',
      cover_uri: null, lifecycle_status: 'published',
      courses: [{ course_id: 'course', course_run_id: 'run', code: 'EN3', name: 'English',
        content_version_id: 'version-uuid', content_version_sequence: 2,
        content_version_published_at: '2026-10-10T12:00:00Z' }],
    };
    const plan: StudyPlan = { id: 'plan', book_id: 'book', course_id: 'course',
      content_version_id: 'version-uuid', name: '默认计划', modules: [] };
    const label = textbookVersionLabel(book, plan, getLabels('zh'), 'zh');
    expect(label).toContain('外研社版 · 内容版本 2');
    expect(label).not.toContain('version-uuid');
  });

  it('shows source filename, page and excerpt without exposing chunk IDs', () => {
    const html = renderToStaticMarkup(<EvidenceSources ids={['chunk-uuid']} sources={[{
      chunk_id: 'chunk-uuid', relative_path: '小学/英语/三年级上册.pdf',
      anchor_type: 'page', anchor_value: '9', text_excerpt: "Hello, I'm Sam!",
    }]} labels={getLabels('zh')} />);
    expect(html).toContain('三年级上册.pdf · 第 9 页');
    expect(html).toContain('Hello, I&#x27;m Sam!');
    expect(html).not.toContain('chunk-uuid');
  });

  it('uses an honest fallback when evidence metadata cannot be resolved', () => {
    const html = renderToStaticMarkup(<EvidenceSources ids={['chunk-uuid']} sources={[]} labels={getLabels('zh')} />);
    expect(html).toContain('证据来源暂不可用');
    expect(html).not.toContain('chunk-uuid');
  });

  it('identifies unreadable OCR without inventing an excerpt', () => {
    const html = renderToStaticMarkup(<EvidenceSources ids={['chunk-uuid']} sources={[{
      chunk_id: 'chunk-uuid', relative_path: '小学/英语/三年级上册.pdf',
      anchor_type: 'page', anchor_value: '7', text_excerpt: '',
    }]} labels={getLabels('zh')} />);
    expect(html).toContain('三年级上册.pdf · 第 7 页');
    expect(html).toContain('此页文字识别质量不足，请对照原教材。');
    expect(html).not.toContain('chunk-uuid');
  });
});
