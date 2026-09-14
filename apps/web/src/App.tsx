import { useState, useRef, useCallback, useEffect } from 'react';
import type { ChatCitation, Course, MemoryFact } from './types';
import {
  exportMemories,
  getMemoryConsent,
  listCourses,
  listMemories,
  setMemoryConsent,
  streamChat,
  updateMemory,
} from './api';
import { RichText } from './RichText';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  citations: ChatCitation[];
  abstained?: string;
  error?: string;
}

export default function App() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [memories, setMemories] = useState<MemoryFact[]>([]);
  const [showMemory, setShowMemory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const queryRef = useRef<HTMLInputElement>(null);
  const streamControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    listCourses()
      .then(setCourses)
      .catch(console.error);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => () => streamControllerRef.current?.abort(), []);

  const refreshMemory = useCallback(async () => {
    if (!selectedCourseId) {
      setMemoryEnabled(false);
      setMemories([]);
      return;
    }
    const [enabled, facts] = await Promise.all([
      getMemoryConsent(selectedCourseId),
      listMemories(selectedCourseId),
    ]);
    setMemoryEnabled(enabled);
    setMemories(facts);
  }, [selectedCourseId]);

  useEffect(() => {
    if (!selectedCourseId) return;
    let active = true;
    Promise.all([
      getMemoryConsent(selectedCourseId),
      listMemories(selectedCourseId),
    ])
      .then(([enabled, facts]) => {
        if (!active) return;
        setMemoryEnabled(enabled);
        setMemories(facts);
      })
      .catch(console.error);
    return () => {
      active = false;
    };
  }, [selectedCourseId]);

  const handleCourseChange = (courseId: string) => {
    streamControllerRef.current?.abort();
    setSelectedCourseId(courseId);
    setSessionId(undefined);
    setMessages([]);
    setMemoryEnabled(false);
    setMemories([]);
    setShowMemory(false);
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = queryRef.current?.value?.trim() ?? '';
      if (!q || !selectedCourseId || streaming) return;

      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        text: q,
        citations: [],
      };
      const assistantId = crypto.randomUUID();
      const assistantMsg: Message = {
        id: assistantId,
        role: 'assistant',
        text: '',
        citations: [],
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      if (queryRef.current) queryRef.current.value = '';
      setStreaming(true);

      const updateAssistant = (update: (message: Message) => Message) => {
        setMessages((prev) =>
          prev.map((message) => (message.id === assistantId ? update(message) : message)),
        );
      };
      const controller = new AbortController();
      streamControllerRef.current = controller;

      try {
        await streamChat(
          selectedCourseId,
          { query: q, session_id: sessionId },
          {
            onToken: (token) => {
              updateAssistant((message) => ({ ...message, text: message.text + token }));
            },
            onCitation: (citation) => {
              updateAssistant((message) => ({
                ...message,
                citations: message.citations.some((item) => item.chunk_id === citation.chunk_id)
                  ? message.citations
                  : [...message.citations, citation],
              }));
            },
            onAbstained: (reason) => {
              updateAssistant((message) => ({ ...message, abstained: reason }));
            },
            onDone: (_traceId, _answerTokens, nextSessionId) => {
              if (nextSessionId) setSessionId(nextSessionId);
              refreshMemory().catch(console.error);
            },
            onError: (detail) => {
              updateAssistant((message) => ({ ...message, error: detail }));
            },
          },
          controller.signal,
        );
      } finally {
        if (streamControllerRef.current === controller) streamControllerRef.current = null;
        setStreaming(false);
      }
    },
    [refreshMemory, selectedCourseId, sessionId, streaming],
  );

  const handleMemoryAction = async (
    fact: MemoryFact,
    action: 'correct' | 'pin' | 'unpin' | 'delete',
  ) => {
    let value: string | undefined;
    if (action === 'correct') {
      value = window.prompt('Correct this memory', fact.normalized_value)?.trim();
      if (!value || value === fact.normalized_value) return;
    }
    await updateMemory(fact.id, action, value);
    await refreshMemory();
  };

  const handleExport = async () => {
    const blob = await exportMemories(selectedCourseId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `course-memory-${selectedCourseId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={styles.root}>
      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Course Tutor</h1>
        <span style={styles.hint}>AI-generated tutoring guidance</span>
        {courses.length > 0 && (
          <select
            value={selectedCourseId}
            onChange={(e) => handleCourseChange(e.target.value)}
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
        {selectedCourseId && (
          <button type="button" onClick={() => setShowMemory((value) => !value)}>
            Memory ({memories.filter((fact) => fact.status === 'active').length})
          </button>
        )}
      </header>

      {showMemory && selectedCourseId && (
        <aside style={styles.memoryPanel} aria-label="Learner memory">
          <label>
            <input
              type="checkbox"
              checked={memoryEnabled}
              onChange={async (event) => {
                await setMemoryConsent(selectedCourseId, event.target.checked);
                await refreshMemory();
              }}
            />{' '}
            Remember compact learning preferences for this course
          </label>
          <button type="button" onClick={handleExport}>Export</button>
          {memories.length === 0 ? (
            <span style={styles.hint}> No saved facts.</span>
          ) : (
            <ul>
              {memories.map((fact) => (
                <li key={fact.id}>
                  <strong>{fact.type}</strong>: {fact.normalized_value}{' '}
                  <small title={fact.reason}>{fact.status} · Why?</small>{' '}
                  <button
                    type="button"
                    onClick={() => handleMemoryAction(fact, fact.pinned ? 'unpin' : 'pin')}
                  >
                    {fact.pinned ? 'Unpin' : 'Pin'}
                  </button>{' '}
                  <button type="button" onClick={() => handleMemoryAction(fact, 'correct')}>
                    Correct
                  </button>{' '}
                  <button type="button" onClick={() => handleMemoryAction(fact, 'delete')}>
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}

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
              <RichText text={msg.text} />
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

        <div ref={messagesEndRef} />
      </main>

      {/* Input */}
      <footer style={styles.footer}>
        <form onSubmit={handleSubmit} style={styles.form}>
          <input
            ref={queryRef}
            defaultValue=""
            placeholder={
              selectedCourseId ? 'Ask about the course…' : 'Select a course first…'
            }
            disabled={streaming || !selectedCourseId}
            style={styles.input}
          />
          <button type="submit" disabled={streaming || !selectedCourseId} style={styles.button}>
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
  memoryPanel: {
    padding: '12px 20px',
    borderBottom: '1px solid #e5e7eb',
    backgroundColor: '#fff',
    fontSize: '13px',
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
