import type { ChatCitation, ChatRequest, Course } from './types';

const API_BASE = '/v1';

export async function listCourses(): Promise<Course[]> {
  const res = await fetch(`${API_BASE}/courses`);
  if (!res.ok) throw new Error(`listCourses failed: ${res.status}`);
  return res.json();
}

export async function getCourse(courseId: string): Promise<Course> {
  const res = await fetch(`${API_BASE}/courses/${courseId}`);
  if (!res.ok) throw new Error(`getCourse failed: ${res.status}`);
  return res.json();
}

export interface ChatStreamCallbacks {
  onToken: (text: string) => void;
  onCitation: (citation: ChatCitation) => void;
  onAbstained: (reason: string) => void;
  onDone: (traceId: string | null, answerTokens: number) => void;
  onError: (detail: string) => void;
}

export async function streamChat(
  courseId: string,
  body: ChatRequest,
  callbacks: ChatStreamCallbacks,
): Promise<void> {
  const response = await fetch(`${API_BASE}/courses/${courseId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body }),
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

  // SSE parse: each chunk is "event: <type>\ndata: <json>\n\n"
  const CONTROLLER = { cancelled: false };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done || CONTROLLER.cancelled) break;

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
            const d = data as { trace_id: string | null; answer_tokens: number };
            callbacks.onDone(d.trace_id, d.answer_tokens);
            break;
          }
          case 'error': {
            const d = data as { detail: string };
            callbacks.onError(d.detail);
            break;
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
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
    headers: { 'Content-Type': 'application/json' },
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
