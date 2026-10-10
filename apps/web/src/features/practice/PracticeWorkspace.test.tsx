import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { AnswerInput } from './PracticeWorkspace';
import type { Exercise } from '../../api/practice';
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
