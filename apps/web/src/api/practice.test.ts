import { afterEach, describe, expect, it, vi } from 'vitest';
import { practiceApi } from './practice';

afterEach(() => vi.unstubAllGlobals());

describe('Hiruzen API client', () => {
  it('encodes catalog filters and sends the same bearer scope', async () => {
    const fetchMock = vi.fn(async (...args: [string, RequestInit?]) => { void args; return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }); });
    vi.stubGlobal('fetch', fetchMock);
    await practiceApi.books({ q: '英语 三年级', education_level: 'primary', publisher: '外研社' });
    const [url, optionsValue] = fetchMock.mock.calls[0];
    const options = optionsValue!;
    expect(url).toContain('/v1/practice/catalog/books?');
    expect(new URL(url, 'http://localhost').searchParams.get('q')).toBe('英语 三年级');
    expect(new URL(url, 'http://localhost').searchParams.get('publisher')).toBe('外研社');
    expect((options.headers as Record<string, string>).Authorization).toMatch(/^Bearer /);
  });

  it('submits only the learner answer and idempotency key', async () => {
    const fetchMock = vi.fn(async (...args: [string, RequestInit?]) => { void args; return new Response(JSON.stringify({ outcome: 'incorrect', released_answer: null }), { status: 200 }); });
    vi.stubGlobal('fetch', fetchMock);
    await practiceApi.submit('set-1', 'exercise-1', 'B', 'request-1');
    const [url, optionsValue] = fetchMock.mock.calls[0];
    const options = optionsValue!;
    expect(url).toBe('/v1/practice/sets/set-1/exercises/exercise-1/attempts');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string)).toEqual({ answer: 'B' });
    expect((options.headers as Record<string, string>)['Idempotency-Key']).toBe('request-1');
  });

  it('treats inaccessible resume as an API error rather than leaking a cursor', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })));
    await expect(practiceApi.resume()).rejects.toMatchObject({ status: 404 });
  });
});
