import { useCallback, useState } from 'react';
import { practiceApi } from './api/practice';
import type { Language, Resume } from './api/practice';
import { Catalog } from './features/catalog/Catalog';
import { PracticeWorkspace } from './features/practice/PracticeWorkspace';
import { LanguageSelector } from './features/settings/LanguageSelector';
import { StudyDashboard } from './features/study/StudyDashboard';
import { TutorChat } from './features/tutor/TutorChat';
import { getLabels, loadLanguage, saveLanguage } from './i18n';
import './Hiruzen.css';

type View = 'catalog' | 'study' | 'tutor' | 'book';

export default function HiruzenApp() {
  const [language, setLanguage] = useState<Language>(loadLanguage);
  const [view, setView] = useState<View>('catalog');
  const [bookId, setBookId] = useState('');
  const [resume, setResume] = useState<Resume | null>(null);
  const [revision, setRevision] = useState(0);
  const [courseId, setCourseId] = useState('');
  const [error, setError] = useState('');
  const labels = getLabels(language);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const openBook = (id: string, nextResume?: Resume) => {
    setBookId(id); setResume(nextResume ?? null); setView('book');
    practiceApi.courses(id).then((courses) => setCourseId(courses[0]?.course_id ?? '')).catch(() => setCourseId(''));
  };
  const changeLanguage = (value: Language) => { setLanguage(value); saveLanguage(value); };

  return <div className="hiruzen-app" lang={language === 'en' ? 'en' : 'zh'}>
    <header className="hiruzen-header">
      <div><h1>Hiruzen</h1><p>{labels.aiNotice}</p></div>
      <nav aria-label="Hiruzen" className="hiruzen-nav">
        <button type="button" aria-current={view === 'catalog' || view === 'book' ? 'page' : undefined} onClick={() => setView('catalog')}>{labels.discover}</button>
        <button type="button" aria-current={view === 'study' ? 'page' : undefined} onClick={() => setView('study')}>{labels.study}</button>
        <button type="button" aria-current={view === 'tutor' ? 'page' : undefined} onClick={() => setView('tutor')}>{labels.tutor}</button>
      </nav>
      <LanguageSelector language={language} onChange={changeLanguage} labels={labels} />
    </header>
    <main className="hiruzen-main">
      {view === 'catalog' && <Catalog labels={labels} onOpen={(id) => openBook(id)} />}
      {view === 'study' && <StudyDashboard labels={labels} revision={revision} onResume={(item) => openBook(item.book_id, item)} onOpenBook={(id) => openBook(id)} />}
      {view === 'book' && <PracticeWorkspace key={bookId + (resume?.practice_set_id ?? '')} bookId={bookId} language={language} labels={labels} resume={resume ? { setId: resume.practice_set_id, exerciseId: resume.exercise_id, attemptNumber: resume.attempt_number, released: resume.released } : undefined} onProgress={refresh} onBack={() => setView('catalog')} />}
      {view === 'tutor' && <section>
        <h2>{labels.liveChat}</h2>
        {!courseId && <p>{labels.selectBookForTutor}</p>}
        {error && <p role="alert">{error}</p>}
        <button type="button" onClick={async () => {
          try {
            const current = await practiceApi.resume();
            if (current) { setCourseId(current.course_id); setError(''); }
            else setError(labels.emptyProgress);
          } catch (err) { setError((err as Error).message); }
        }}>{labels.resume}</button>
        {courseId && <TutorChat courseId={courseId} language={language} labels={labels} />}
      </section>}
    </main>
  </div>;
}
