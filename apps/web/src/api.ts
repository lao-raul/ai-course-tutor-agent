import type { ChatCitation, ChatRequest, Course, MemoryFact } from './types';

const API_BASE = '/v1';
const LOCAL_AUTH_TOKEN = import.meta.env.VITE_LOCAL_AUTH_TOKEN ?? 'local-dev-token';
const authHeaders = { Authorization: `Bearer ${LOCAL_AUTH_TOKEN}` };

function requestHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    ...authHeaders,
    'X-Correlation-ID': crypto.randomUUID(),
    ...extra,
  };
}

export async function listCourses(): Promise<Course[]> {
  const res = await fetch(`${API_BASE}/courses`, { headers: requestHeaders() });
  if (!res.ok) throw new Error(`listCourses failed: ${res.status}`);
  return res.json();
}

export async function getCourse(courseId: string): Promise<Course> {
  const res = await fetch(`${API_BASE}/courses/${courseId}`, { headers: requestHeaders() });
  if (!res.ok) throw new Error(`getCourse failed: ${res.status}`);
  return res.json();
}

export interface ChatStreamCallbacks {
  onToken: (text: string) => void;
  onCitation: (citation: ChatCitation) => void;
  onAbstained: (reason: string) => void;
  onDone: (traceId: string | null, answerTokens: number, sessionId: string | null) => void;
  onError: (detail: string) => void;
}

export async function streamChat(
  courseId: string,
  body: ChatRequest,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/courses/${courseId}/chat`, {
    method: 'POST',
    headers: requestHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'unknown' }));
    callbacks.onError(err.detail ?? `HTTP ${response.status}`);
    return;
  }

  if (!response.body) {
    callbacks.onError('no response body');
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete events in buffer
      while (buffer.includes('\n\n')) {
        const idx = buffer.indexOf('\n\n');
        const eventBlock = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        const eventLine = eventBlock.split('\n').find((l) => l.startsWith('event:'));
        const dataLine = eventBlock.split('\n').find((l) => l.startsWith('data:'));
        if (!eventLine || !dataLine) continue;

        const eventType = eventLine.slice('event:'.length).trim();
        const jsonStr = dataLine.slice('data:'.length).trim();
        let data: unknown;
        try {
          data = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        switch (eventType) {
          case 'token': {
            const d = data as { text: string };
            callbacks.onToken(d.text ?? '');
            break;
          }
          case 'citation': {
            const d = data as ChatCitation;
            callbacks.onCitation(d);
            break;
          }
          case 'abstained': {
            const d = data as { reason: string };
            callbacks.onAbstained(d.reason);
            break;
          }
          case 'done': {
            const d = data as {
              trace_id: string | null;
              answer_tokens: number;
              session_id?: string | null;
            };
            callbacks.onDone(d.trace_id, d.answer_tokens, d.session_id ?? null);
            return;
          }
          case 'error': {
            const d = data as { detail: string };
            callbacks.onError(d.detail);
            break;
          }
        }
      }
    }
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) {
      callbacks.onError(error instanceof Error ? error.message : 'stream failed');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function listMemories(courseId: string): Promise<MemoryFact[]> {
  const res = await fetch(`${API_BASE}/memories?course_id=${encodeURIComponent(courseId)}`, {
    headers: requestHeaders(),
  });
  if (!res.ok) throw new Error(`listMemories failed: ${res.status}`);
  return res.json();
}

export async function getMemoryConsent(courseId: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/courses/${courseId}/memory-consent`, {
    headers: requestHeaders(),
  });
  if (!res.ok) throw new Error(`getMemoryConsent failed: ${res.status}`);
  return (await res.json()).enabled as boolean;
}

export async function setMemoryConsent(courseId: string, enabled: boolean): Promise<void> {
  const res = await fetch(`${API_BASE}/courses/${courseId}/memory-consent`, {
    method: 'PUT',
    headers: requestHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`setMemoryConsent failed: ${res.status}`);
}

export async function updateMemory(
  memoryId: string,
  action: 'correct' | 'pin' | 'unpin' | 'delete',
  normalizedValue?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/memories/${memoryId}`, {
    method: 'PATCH',
    headers: requestHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      action,
      ...(normalizedValue === undefined ? {} : { normalized_value: normalizedValue }),
    }),
  });
  if (!res.ok) throw new Error(`updateMemory failed: ${res.status}`);
}

export async function exportMemories(courseId: string): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/memories/export?course_id=${encodeURIComponent(courseId)}`,
    { headers: requestHeaders() },
  );
  if (!res.ok) throw new Error(`exportMemories failed: ${res.status}`);
  return res.blob();
}

export async function ingestCourse(
  sourcePath: string,
  tenantSlug: string,
  tenantName: string,
  courseCode: string,
  courseName: string,
  courseLevel: string,
): Promise<{ course_id: string; job_id: string; version_id: string }> {
  const res = await fetch(`${API_BASE}/admin/ingest`, {
    method: 'POST',
    headers: requestHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      source_path: sourcePath,
      tenant_slug: tenantSlug,
      tenant_name: tenantName,
      course_code: courseCode,
      course_name: courseName,
      course_level: courseLevel,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`ingest failed: ${res.status} ${JSON.stringify(err)}`);
  }
  return res.json();
}
