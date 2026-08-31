import { useState, useRef, useCallback, useEffect } from 'react';
import type { ChatCitation, Course } from './types';
import { listCourses, streamChat } from './api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  citations: ChatCitation[];
  abstained?: string;
  error?: string;
}

const ACCESS_LABEL_OPTIONS = [
  { value: 'public', label: 'Public' },
  { value: 'enrolled', label: 'Enrolled' },
] as const;

export default function App() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string>('');
  const [accessLabel, setAccessLabel] = useState<'public' | 'enrolled'>('enrolled');
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [currentCitations, setCurrentCitations] = useState<ChatCitation[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listCourses()
      .then(setCourses)
      .catch(console.error);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentCitations]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!query.trim() || !selectedCourseId || streaming) return;

      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        text: query.trim(),
        citations: [],
      };
      setMessages((prev) => [...prev, userMsg]);
      setQuery('');
      setStreaming(true);
      setCurrentCitations([]);

      let fullText = '';
      const citations: ChatCitation[] = [];

      await streamChat(
        selectedCourseId,
        { query: userMsg.text, access_label: accessLabel },
        {
          onToken: (token) => {
            fullText += token;
          },
          onCitation: (cit) => {
            citations.push(cit);
            setCurrentCitations((prev) => [...prev, cit]);
          },
          onAbstained: (reason) => {
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: 'assistant',
                text: '',
                citations: [],
                abstained: reason,
              },
            ]);
          },
          onDone: () => {
            if (fullText) {
              setMessages((prev) => [
                ...prev,
                { id: crypto.randomUUID(), role: 'assistant', text: fullText, citations: [...citations] },
              ]);
            }
          },
          onError: (detail) => {
            setMessages((prev) => [
              ...prev,
              { id: crypto.randomUUID(), role: 'assistant', text: '', citations: [], error: detail },
            ]);
          },
        },
      );

      setStreaming(false);
    },
    [selectedCourseId, accessLabel, streaming],
  );

  return (
    <div style={styles.root}>
      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Course Tutor</h1>
        {courses.length > 0 && (
          <select
            value={selectedCourseId}
            onChange={(e) => setSelectedCourseId(e.target.value)}
            style={styles.select}
          >
            <option value="">Select a course…</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        )}
      </header>

      {/* Chat area */}
      <main style={styles.chatArea}>
        {messages.length === 0 && !streaming && (
          <div style={styles.empty}>
            <p>Ask a question about the selected course.</p>
            <p style={styles.hint}>
              Example: "What is covered in Week 3 about Bayesian networks?"
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} style={msg.role === 'user' ? styles.userMsg : styles.assistantMsg}>
            <div style={styles.roleLabel}>{msg.role === 'user' ? 'You' : 'Assistant'}</div>
            {msg.abstained ? (
              <p style={styles.abstained}>
                I couldn't find relevant material in the course content for that question. Please try rephrasing or ask about a different topic.
              </p>
            ) : msg.error ? (
              <p style={styles.error}>Error: {msg.error}</p>
            ) : (
              <p style={styles.msgText}>{msg.text}</p>
            )}
            {msg.citations.length > 0 && (
              <div style={styles.citations}>
                <div style={styles.citationsLabel}>Sources:</div>
                {msg.citations.map((cit, i) => (
                  <div key={i} style={styles.citation}>
                    <span style={styles.citSource}>{cit.relative_path}</span>
                    <span style={styles.citAnchor}>
                      {' '}({cit.anchor_type} {cit.anchor_value})
                    </span>
                    <div style={styles.citExcerpt}>{cit.text_excerpt}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {/* Live citations while streaming */}
        {streaming && currentCitations.length > 0 && (
          <div style={styles.assistantMsg}>
            <div style={styles.roleLabel}>Assistant</div>
            <div style={styles.citations}>
              <div style={styles.citationsLabel}>Sources found:</div>
              {currentCitations.map((cit, i) => (
                <div key={i} style={styles.citation}>
                  <span style={styles.citSource}>{cit.relative_path}</span>
                  <span style={styles.citAnchor}>
                    {' '}({cit.anchor_type} {cit.anchor_value})
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Input */}
      <footer style={styles.footer}>
        <form onSubmit={handleSubmit} style={styles.form}>
          <select
            value={accessLabel}
            onChange={(e) => setAccessLabel(e.target.value as 'public' | 'enrolled')}
            style={styles.accessSelect}
            disabled={streaming}
          >
            {ACCESS_LABEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              selectedCourseId ? 'Ask about the course…' : 'Select a course first…'
            }
            disabled={streaming || !selectedCourseId}
            style={styles.input}
          />
          <button type="submit" disabled={streaming || !query.trim() || !selectedCourseId} style={styles.button}>
            {streaming ? '…' : 'Send'}
          </button>
        </form>
      </footer>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    fontFamily: 'system-ui, sans-serif',
    backgroundColor: '#f9fafb',
  },
  header: {
    padding: '12px 20px',
    borderBottom: '1px solid #e5e7eb',
    backgroundColor: '#fff',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  },
  title: {
    margin: 0,
    fontSize: '18px',
    fontWeight: 700,
    color: '#111827',
  },
  select: {
    fontSize: '14px',
    padding: '6px 10px',
    border: '1px solid #d1d5db',
    borderRadius: '6px',
    backgroundColor: '#fff',
    color: '#374151',
  },
  chatArea: {
    flex: 1,
    overflowY: 'auto',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  empty: {
    textAlign: 'center',
    color: '#6b7280',
    marginTop: '80px',
  },
  hint: {
    fontSize: '13px',
    color: '#9ca3af',
  },
  userMsg: {
    alignSelf: 'flex-end',
    maxWidth: '70%',
  },
  assistantMsg: {
    alignSelf: 'flex-start',
    maxWidth: '80%',
  },
  roleLabel: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#9ca3af',
    marginBottom: '2px',
    textTransform: 'uppercase',
  },
  msgText: {
    margin: 0,
    fontSize: '15px',
    lineHeight: 1.6,
    color: '#111827',
    whiteSpace: 'pre-wrap',
  },
  abstained: {
    margin: 0,
    fontSize: '14px',
    color: '#6b7280',
    fontStyle: 'italic',
  },
  error: {
    margin: 0,
    fontSize: '14px',
    color: '#ef4444',
  },
  citations: {
    marginTop: '8px',
    borderTop: '1px solid #e5e7eb',
    paddingTop: '6px',
  },
  citationsLabel: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#9ca3af',
    textTransform: 'uppercase',
    marginBottom: '4px',
  },
  citation: {
    fontSize: '12px',
    marginBottom: '4px',
  },
  citSource: {
    fontWeight: 600,
    color: '#374151',
  },
  citAnchor: {
    color: '#6b7280',
  },
  citExcerpt: {
    color: '#9ca3af',
    fontStyle: 'italic',
    marginTop: '1px',
    whiteSpace: 'pre-wrap',
  },
  footer: {
    borderTop: '1px solid #e5e7eb',
    padding: '12px 20px',
    backgroundColor: '#fff',
  },
  form: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  accessSelect: {
    fontSize: '13px',
    padding: '8px 10px',
    border: '1px solid #d1d5db',
    borderRadius: '6px',
  },
  input: {
    flex: 1,
    fontSize: '15px',
    padding: '8px 12px',
    border: '1px solid #d1d5db',
    borderRadius: '6px',
    outline: 'none',
  },
  button: {
    padding: '8px 16px',
    fontSize: '14px',
    fontWeight: 600,
    backgroundColor: '#111827',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
  },
};
