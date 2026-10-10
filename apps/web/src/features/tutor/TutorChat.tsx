import { useEffect, useRef, useState } from 'react';
import { streamChat } from '../../api';
import type { ChatCitation } from '../../types';
import { RichText } from '../../RichText';
import type { Language } from '../../api/practice';
import type { Labels } from '../../i18n';

interface TutorMessage { id: string; role: 'learner' | 'tutor'; text: string; citations: ChatCitation[]; error?: string }
interface Props {
  courseId: string;
  language: Language;
  labels: Labels;
  exercise?: { id: string; prompt: string; attemptNumber: number; released: boolean };
}

export function TutorChat({ courseId, language, labels, exercise }: Props) {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<TutorMessage[]>([]);
  const [sessionId, setSessionId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const exerciseId = exercise?.id;
  useEffect(() => {
    controller.current?.abort();
    setSessionId(undefined);
    setMessages([]);
    return () => controller.current?.abort();
  }, [courseId, exerciseId]);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text || busy) return;
    const id = crypto.randomUUID();
    const newController = new AbortController();
    controller.current = newController;
    setQuery('');
    setBusy(true);
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'learner', text, citations: [] }, { id, role: 'tutor', text: '', citations: [] }]);
    const update = (fn: (item: TutorMessage) => TutorMessage) =>
      setMessages((current) => current.map((item) => item.id === id ? fn(item) : item));
    try {
      await streamChat(courseId, {
        // The exercise is context, never a textbook citation or an answer key.
        query: exercise ? `Current practice question: ${exercise.prompt.slice(0, 850)}\nLearner asks: ${text}` : text,
        session_id: sessionId,
        assessment_mode: Boolean(exercise),
        // Never claim three attempts until the Practice API explicitly released the answer.
        attempt_number: exercise?.released ? 3 : Math.min(2, Math.max(1, exercise?.attemptNumber ?? 1)),
        response_language: language === 'zh' ? 'chinese' : language === 'en' ? 'english' : 'bilingual',
      }, {
        onToken: (token) => update((item) => ({ ...item, text: item.text + token })),
        onCitation: (citation) => update((item) => ({ ...item, citations: item.citations.some((old) => old.chunk_id === citation.chunk_id) ? item.citations : [...item.citations, citation] })),
        onAbstained: (reason) => update((item) => ({ ...item, error: reason })),
        onDone: (_trace, _tokens, nextSession) => { if (nextSession) setSessionId(nextSession); },
        onError: (detail) => update((item) => ({ ...item, error: detail })),
      }, newController.signal);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) update((item) => ({ ...item, error: (error as Error).message }));
    } finally {
      if (controller.current === newController) controller.current = null;
      setBusy(false);
    }
  };

  return <section className="hiruzen-tutor" aria-label={exercise ? labels.ask : labels.liveChat}>
    <h3>{exercise ? labels.ask : labels.liveChat}</h3>
    <p className="hiruzen-note">{labels.aiNotice}</p>
    <div aria-live="polite">
      {messages.map((item) => <article key={item.id} className="hiruzen-message">
        <strong>{item.role === 'learner' ? labels.question : labels.reply}</strong>
        {item.error ? <p role="alert">{item.error}</p> : <RichText text={item.text} />}
        {item.role === 'tutor' && item.text && (item.citations.length ?
          <details><summary>{labels.sources} ({item.citations.length})</summary><ul>{item.citations.map((citation) => <li key={citation.chunk_id}>{citation.relative_path} ({citation.anchor_type} {citation.anchor_value}) — {citation.text_excerpt}</li>)}</ul></details>
          : !busy && <p className="hiruzen-note">{labels.noCitation}</p>)}
      </article>)}
    </div>
    <form onSubmit={send} className="hiruzen-search">
      <label className="hiruzen-grow">{labels.ask}
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={labels.askHint} maxLength={1000} />
      </label>
      <button type="submit" disabled={busy || !query.trim()}>{busy ? labels.loading : labels.send}</button>
    </form>
  </section>;
}
