import { useEffect, useState } from 'react';
import { practiceApi } from '../../api/practice';
import type { Resume, StudyStatus } from '../../api/practice';
import type { Labels } from '../../i18n';

interface Props {
  labels: Labels;
  revision: number;
  onResume: (value: Resume) => void;
  onOpenBook: (bookId: string) => void;
}

export function StudyDashboard({ labels, revision, onResume, onOpenBook }: Props) {
  const [status, setStatus] = useState<StudyStatus>();
  const [resume, setResume] = useState<Resume | null>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    Promise.all([practiceApi.status(), practiceApi.resume()]).then(([nextStatus, nextResume]) => {
      if (active) { setStatus(nextStatus); setResume(nextResume); setError(''); }
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [revision]);
  return <section aria-label={labels.study}>
    <h2>{labels.study}</h2>
    {error && <p role="alert" className="hiruzen-error">{labels.error}: {error}</p>}
    {!status && !error && <p role="status">{labels.loading}</p>}
    {resume && <div className="hiruzen-card">
      <button type="button" onClick={() => onResume(resume)}>{labels.resume}</button>{' '}
      <button type="button" onClick={async () => {
        try { await practiceApi.clearResume(crypto.randomUUID()); setResume(null); }
        catch (err) { setError((err as Error).message); }
      }}>{labels.clear}</button>
    </div>}
    {status?.sets.length === 0 && <p>{labels.emptyProgress}</p>}
    <ul className="hiruzen-books">
      {status?.sets.map((item) => <li key={item.practice_set_id}>
        <h3>{labels.status}: {item.status === 'COMPLETED' ? labels.statusCompleted : item.status === 'IN_PROGRESS' ? labels.statusInProgress : labels.statusNotStarted}</h3>
        <p>{labels.progress}: {item.completed_questions}/{item.total_questions} · {item.correct_questions}/{item.attempted_questions}</p>
        <button type="button" onClick={() => onOpenBook(item.book_id)}>{labels.open}</button>
      </li>)}
    </ul>
  </section>;
}
