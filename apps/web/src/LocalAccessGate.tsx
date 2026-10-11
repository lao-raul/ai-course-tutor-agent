import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { checkAccessToken, getAccessToken, setAccessToken } from './api';
import './LocalAccessGate.css';

type AccessState = 'checking' | 'ready' | 'denied' | 'unavailable';

export function LocalAccessGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AccessState>(() => getAccessToken() ? 'checking' : 'denied');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const token = getAccessToken();
    if (!token) return () => { active = false; };
    checkAccessToken(token)
      .then((response) => {
        if (active) setState(response.ok ? 'ready' : response.status === 401 || response.status === 403 ? 'denied' : 'unavailable');
      })
      .catch(() => { if (active) setState('unavailable'); });
    return () => { active = false; };
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const token = input.trim();
    if (!token) return;
    setError('');
    setState('checking');
    try {
      const response = await checkAccessToken(token);
      if (response.ok) {
        setAccessToken(token);
        setInput('');
        setState('ready');
      } else {
        setError(response.status === 401 || response.status === 403 ? '令牌无效或没有访问权限。' : `服务暂时不可用（HTTP ${response.status}）。`);
        setState('denied');
      }
    } catch {
      setError('无法连接服务，请确认本地部署正在运行。');
      setState('denied');
    }
  };

  if (state === 'ready') return <>
    {children}
    <div className="local-access-toolbar"><button type="button" onClick={() => { setInput(''); setError(''); setState('denied'); }}>更换访问令牌 / Change access token</button></div>
  </>;

  return <main className="local-access-page">
    <section className="local-access-card" aria-label="Local access">
      <h1>Hiruzen · 本地访问</h1>
      {state === 'checking' ? <p role="status">正在验证访问权限…</p> : <>
        <p>请输入当前部署的访问令牌。令牌只保存在这个浏览器会话中，不会写入前端镜像。</p>
        {state === 'unavailable' && <p role="alert">服务暂时不可用，请确认本地部署正在运行。</p>}
        {error && <p role="alert">{error}</p>}
        <form onSubmit={submit}>
          <label htmlFor="local-access-token">访问令牌 / Access token</label>
          <input id="local-access-token" type="password" autoComplete="off" value={input} onChange={(event) => setInput(event.target.value)} required />
          <button type="submit">连接 / Connect</button>
        </form>
        {state === 'unavailable' && <button type="button" onClick={() => window.location.reload()}>重试 / Retry</button>}
      </>}
    </section>
  </main>;
}
