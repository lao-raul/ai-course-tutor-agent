import { useEffect, useState } from 'react';
import { practiceApi } from '../../api/practice';
import type { BookDetail, Difficulty, Exercise, Feedback, Generation, Language, PracticeSet, SetProgress, StudyPlan } from '../../api/practice';
import type { Labels } from '../../i18n';
import { RichText } from '../../RichText';
import { TutorChat } from '../tutor/TutorChat';

interface Props {
  bookId: string;
  language: Language;
  labels: Labels;
  resume?: { setId: string; exerciseId: string; attemptNumber: number; released: boolean };
  onProgress: () => void;
  onBack: () => void;
}

function answerText(answer: string | boolean | string[]): string {
  return Array.isArray(answer) ? answer.join(' / ') : String(answer);
}

export function PracticeWorkspace({ bookId, language, labels, resume, onProgress, onBack }: Props) {
  const [book, setBook] = useState<BookDetail>();
  const [plan, setPlan] = useState<StudyPlan>();
  const [generation, setGeneration] = useState<Generation>();
  const [practiceSet, setPracticeSet] = useState<PracticeSet>();
  const [progress, setProgress] = useState<SetProgress>();
  const [index, setIndex] = useState(0);
  const [attemptNumber, setAttemptNumber] = useState(resume?.attemptNumber ?? 0);
  const [released, setReleased] = useState(resume?.released ?? false);
  const [answer, setAnswer] = useState('');
  const [feedback, setFeedback] = useState<Feedback>();
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState<Difficulty>('standard');
  const [moduleId, setModuleId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reportNotice, setReportNotice] = useState('');
  const [reportReason, setReportReason] = useState<'incorrect' | 'ambiguous' | 'unsafe'>('ambiguous');
  const [reportDetail, setReportDetail] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([practiceApi.book(bookId), practiceApi.plan(bookId)]).then(([nextBook, nextPlan]) => {
      if (active) { setBook(nextBook); setPlan(nextPlan); }
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [bookId]);

  useEffect(() => {
    if (!resume?.setId) return;
    let active = true;
    practiceApi.set(resume.setId).then((value) => {
      if (!active) return;
      setPracticeSet(value);
      const position = value.exercises.findIndex((item) => item.id === resume.exerciseId);
      setIndex(position < 0 ? 0 : position);
      setAttemptNumber(resume.attemptNumber);
      setReleased(resume.released);
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [resume?.setId, resume?.exerciseId, resume?.attemptNumber, resume?.released]);

  useEffect(() => {
    if (!generation || ['ready', 'failed', 'cancelled'].includes(generation.status)) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      try {
        const next = await practiceApi.generation(generation.id);
        if (!active) return;
        setGeneration(next);
      } catch (err) { if (active) setError((err as Error).message); }
    }, 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [generation]);

  useEffect(() => {
    if (generation?.status !== 'ready' || !generation.practice_set_id) return;
    let active = true;
    practiceApi.set(generation.practice_set_id).then((value) => {
      if (active) {
        setPracticeSet(value); setIndex(0); setAttemptNumber(0); setReleased(false); setFeedback(undefined); setAnswer('');
        onProgress();
      }
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [generation?.status, generation?.practice_set_id, onProgress]);

  useEffect(() => {
    if (!practiceSet) return;
    let active = true;
    practiceApi.status().then((value) => {
      if (active) setProgress(value.sets.find((item) => item.practice_set_id === practiceSet.id));
    }).catch(() => undefined);
    return () => { active = false; };
  }, [practiceSet, feedback]);

  const generate = async () => {
    setBusy(true); setError('');
    try {
      const value = await practiceApi.generate(bookId, {
        count, difficulty, language, question_types: ['multiple_choice', 'true_false', 'fill_in_the_blank', 'short_answer'],
        ...(moduleId ? { module_id: moduleId } : {}),
      }, crypto.randomUUID());
      setPracticeSet(undefined); setGeneration(value); onProgress();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  const cancel = async () => {
    if (!generation) return;
    setBusy(true);
    try { setGeneration(await practiceApi.cancelGeneration(generation.id)); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  const exercise = practiceSet?.exercises[index];
  const submit = async (giveUp: boolean) => {
    if (!practiceSet || !exercise || busy || (!giveUp && !answer.trim())) return;
    setBusy(true); setError('');
    try {
      const value = giveUp
        ? await practiceApi.giveUp(practiceSet.id, exercise.id, crypto.randomUUID())
        : await practiceApi.submit(practiceSet.id, exercise.id, exercise.type === 'true_false' ? answer === 'true' : answer, crypto.randomUUID());
      setFeedback(value); setAttemptNumber(value.attempt_number); setReleased(Boolean(value.released_answer)); onProgress();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  const next = () => {
    if (!practiceSet) return;
    const nextId = progress?.next_exercise_id;
    const nextIndex = nextId ? practiceSet.exercises.findIndex((item) => item.id === nextId) : -1;
    setIndex(nextIndex >= 0 && nextIndex !== index ? nextIndex : Math.min(index + 1, practiceSet.exercises.length - 1));
    setAnswer(''); setFeedback(undefined); setAttemptNumber(0); setReleased(false); setReportNotice(''); setReportDetail('');
  };

  return <section className="hiruzen-workspace">
    <button type="button" onClick={onBack}>{labels.back}</button>
    {error && <p role="alert" className="hiruzen-error">{labels.error}: {error}</p>}
    {!book || !plan ? <p role="status">{labels.loading}</p> : <>
      <h2>{book.title}</h2>
      <p>{book.grade} · {book.subject} · {book.publisher} · {book.term}</p>
      <p className="hiruzen-note">{labels.aiNotice}</p>
      <h3>{labels.plan}: {plan.name}</h3>
      <label>{labels.course}
        <span>{book.courses.find((course) => course.course_id === plan.course_id)?.name ?? plan.course_id}</span>
      </label>
      <p>{labels.sourceVersion}: <code>{plan.content_version_id}</code></p>
      {!practiceSet && <div className="hiruzen-controls">
        <label>{labels.plan}
          <select value={moduleId} onChange={(event) => setModuleId(event.target.value)}>
            <option value="">{labels.bookLevel}</option>
            {plan.modules.map((module) => <option key={module.id} value={module.id}>{module.title}</option>)}
          </select>
        </label>
        <label>{labels.questionCount}<input type="number" min={1} max={20} value={count} onChange={(event) => setCount(Math.min(20, Math.max(1, Number(event.target.value) || 1)))} /></label>
        <label>{labels.difficulty}<select value={difficulty} onChange={(event) => setDifficulty(event.target.value as Difficulty)}><option value="introductory">{labels.introductory}</option><option value="standard">{labels.standard}</option><option value="challenge">{labels.challenge}</option></select></label>
        <button type="button" disabled={busy || (generation && !['failed', 'cancelled', 'ready'].includes(generation.status))} onClick={generate}>{labels.generate}</button>
      </div>}
      {generation && !practiceSet && <div role="status">
        <p>{labels.generating}: {generation.status}</p>
        {generation.status === 'failed' && <p role="alert">{generation.error_code ?? labels.error} {generation.retryable ? <button onClick={generate}>{labels.retry}</button> : null}</p>}
        {!['ready', 'failed', 'cancelled'].includes(generation.status) && <button type="button" disabled={busy} onClick={cancel}>{labels.cancel}</button>}
      </div>}
      {practiceSet && exercise && <>
        <p>{labels.progress}: {progress?.completed_questions ?? 0}/{progress?.total_questions ?? practiceSet.exercises.length}</p>
        <div className="hiruzen-question-layout"><div>
          <article className="hiruzen-card" aria-label={labels.question}>
            <h3>{labels.question} {index + 1} / {practiceSet.exercises.length}</h3>
            <RichText text={exercise.prompt} />
            <p className="hiruzen-note">{exercise.type.replace(/_/g, ' ')} · {exercise.difficulty}</p>
            <AnswerInput exercise={exercise} answer={answer} onChange={setAnswer} disabled={busy || Boolean(feedback && ['correct', 'gave_up'].includes(feedback.outcome)) || released} labels={labels} />
            {exercise.type === 'short_answer' && <div><strong>{labels.feedback}:</strong><ul>{exercise.rubric.map((criterion) => <li key={criterion.description}>{criterion.description} ({Math.round(criterion.weight * 100)}%)</li>)}</ul></div>}
            <div className="hiruzen-actions">
              <button type="button" onClick={() => submit(false)} disabled={busy || !answer.trim() || released || feedback?.outcome === 'correct' || feedback?.outcome === 'gave_up'}>{labels.answer}</button>
              <button type="button" onClick={() => submit(true)} disabled={busy || released || feedback?.outcome === 'correct' || feedback?.outcome === 'gave_up'}>{labels.giveUp}</button>
              <button type="button" onClick={next} disabled={index + 1 >= practiceSet.exercises.length}>{labels.next}</button>
            </div>
            {feedback && <div role="status" aria-live="polite" className="hiruzen-feedback">
              <strong>{feedback.outcome === 'gave_up' ? labels.gaveUp : labels[feedback.outcome]}</strong>
              {feedback.hint && <p>{labels.hint}: {feedback.hint}</p>}
              {feedback.released_answer && <div><strong>{labels.revealed}: {answerText(feedback.released_answer.answer)}</strong><RichText text={feedback.released_answer.rationale} /></div>}
            </div>}
            <details><summary>{labels.sources} ({exercise.evidence_citation_ids.length})</summary><ul>{exercise.evidence_citation_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul></details>
            <details><summary>{labels.report}</summary><div className="hiruzen-controls">
              <label>{labels.reportReason}<select value={reportReason} onChange={(event) => setReportReason(event.target.value as typeof reportReason)}><option value="incorrect">{labels.reportIncorrect}</option><option value="ambiguous">{labels.reportAmbiguous}</option><option value="unsafe">{labels.reportUnsafe}</option></select></label>
              <label>{labels.reportDetail}<input value={reportDetail} maxLength={1000} onChange={(event) => setReportDetail(event.target.value)} /></label>
              <button type="button" onClick={async () => { try { await practiceApi.report(exercise.id, reportReason, reportDetail.trim()); setReportNotice(labels.reportSent); } catch (err) { setError((err as Error).message); } }}>{labels.report}</button>
            </div></details>
            {reportNotice && <p role="status">{reportNotice}</p>}
          </article>
        </div><TutorChat key={exercise.id} courseId={practiceSet.course_id} language={language} labels={labels} exercise={{ id: exercise.id, prompt: exercise.prompt, attemptNumber, released }} /></div>
      </>}
    </>}
  </section>;
}

export function AnswerInput({ exercise, answer, onChange, disabled, labels }: { exercise: Exercise; answer: string; onChange: (value: string) => void; disabled: boolean; labels: Labels }) {
  if (exercise.type === 'multiple_choice') return <fieldset disabled={disabled}><legend>{labels.chooseOne}</legend>{exercise.options.map((option) => <label className="hiruzen-option" key={option.id}><input type="radio" name={`answer-${exercise.id}`} value={option.id} checked={answer === option.id} onChange={() => onChange(option.id)} />{option.text}</label>)}</fieldset>;
  if (exercise.type === 'true_false') return <fieldset disabled={disabled}><legend>{labels.trueFalse}</legend><label className="hiruzen-option"><input type="radio" name={`answer-${exercise.id}`} checked={answer === 'true'} onChange={() => onChange('true')} />{labels.trueLabel}</label><label className="hiruzen-option"><input type="radio" name={`answer-${exercise.id}`} checked={answer === 'false'} onChange={() => onChange('false')} />{labels.falseLabel}</label></fieldset>;
  if (exercise.type === 'short_answer') return <label>{labels.answerField}<textarea rows={4} maxLength={4000} value={answer} onChange={(event) => onChange(event.target.value)} disabled={disabled} /></label>;
  return <label>{labels.answerField}<input maxLength={4000} value={answer} onChange={(event) => onChange(event.target.value)} disabled={disabled} /></label>;
}
