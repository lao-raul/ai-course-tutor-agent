import { afterEach, describe, expect, it, vi } from 'vitest';

import { checkAccessToken, requestHeaders, setAccessToken, streamChat } from './api';

afterEach(() => {
  setAccessToken('');
  vi.unstubAllGlobals();
});

describe('local access token', () => {
  it('uses the current session token for requests and validates a candidate before saving it', async () => {
    const saved = new Map<string, string>();
    vi.stubGlobal('window', { sessionStorage: {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => { saved.set(key, value); },
      removeItem: (key: string) => { saved.delete(key); },
    } });
    const fetchMock = vi.fn(async () => new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    expect((await checkAccessToken('cluster-token')).ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith('/v1/practice/catalog/categories', { headers: { Authorization: 'Bearer cluster-token' } });
    setAccessToken('cluster-token');
    expect(requestHeaders().Authorization).toBe('Bearer cluster-token');
    expect([...saved.values()]).toEqual(['cluster-token']);
  });
});

describe('streamChat', () => {
  it('dispatches split SSE events incrementally and stops after done', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: token\ndata: {"text":"Bayes"}\n'));
        controller.enqueue(encoder.encode('\nevent: token\ndata: {"text":" rule"}\n\n'));
        controller.enqueue(
          encoder.encode(
            'event: citation\ndata: {"chunk_id":"c1","relative_path":"week1.pdf","anchor_type":"page","anchor_value":"2","text_excerpt":"Bayes rule"}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode('event: done\ndata: {"trace_id":"trace-1","answer_tokens":2}\n\n'),
        );
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })));

    const events: string[] = [];
    await streamChat(
      'course-1',
      { query: 'Explain Bayes rule' },
      {
        onToken: (text) => events.push(`token:${text}`),
        onCitation: (citation) => events.push(`citation:${citation.chunk_id}`),
        onAbstained: (reason) => events.push(`abstained:${reason}`),
        onDone: (traceId) => events.push(`done:${traceId}`),
        onError: (detail) => events.push(`error:${detail}`),
      },
    );

    expect(events).toEqual([
      'token:Bayes',
      'token: rule',
      'citation:c1',
      'done:trace-1',
    ]);
  });

  it('does not report an intentional abort as a stream error', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((_resolve, reject) => {
            controller.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const onError = vi.fn();
    const request = streamChat(
      'course-1',
      { query: 'question' },
      {
        onToken: vi.fn(),
        onCitation: vi.fn(),
        onAbstained: vi.fn(),
        onDone: vi.fn(),
        onError,
      },
      controller.signal,
    );
    controller.abort();
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(onError).not.toHaveBeenCalled();
  });
});
