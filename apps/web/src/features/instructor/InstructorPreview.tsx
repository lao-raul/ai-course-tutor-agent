import { useState } from 'react';
import { practiceApi } from '../../api/practice';
import type { InstructorPreview as Preview } from '../../api/practice';

export function InstructorPreview() {
  const [id, setId] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  return <section>
    <h2>教师预览 / Instructor preview</h2>
    <p>AI 生成，仅供教师核查，不是正式考核。AI-generated, not an official assessment.</p>
    <form onSubmit={async (event) => {
      event.preventDefault(); setPreview(null); setError(''); setBusy(true);
      try { setPreview(await practiceApi.preview(id.trim())); }
      catch { setError('无法访问此练习 / Preview unavailable'); }
      finally { setBusy(false); }
    }}>
      <label>练习编号 / Practice set ID<input value={id} onChange={(e) => setId(e.target.value)} required /></label>
      <button disabled={busy} type="submit">查看 / View</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {preview && <>
      <p>教材版本 / Content version: {preview.content_version_id}</p>
      <details><summary>生成记录 / Provenance</summary>
        <p>{preview.model_version} · {preview.prompt_version} · {preview.validator_version}</p>
      </details>
      {preview.exercises.map((item) => <article key={item.id}>
        <h3>{item.ordinal + 1}. {item.question.prompt}</h3>
        <p>AI 生成，非正式考核 / AI-generated, not official</p>
        {item.question.options?.map((option) => <p key={option.id}>{option.id}. {option.text}</p>)}
        <p>参考答案 / Answer: {String(item.question.correct_option_id ?? item.question.answer ?? item.question.acceptable_answers?.join(' / ') ?? item.question.exemplar_answer ?? '')}</p>
        <p>解析 / Rationale: {item.question.rationale}</p>
        {item.question.rubric?.map((criterion, i) => <p key={i}>{criterion.description} ({criterion.weight})</p>)}
        <details><summary>证据与版本 / Evidence and revision</summary>
          <p>{item.revision}</p>
          {item.question.evidence_citation_ids.map((citation) => {
            const source = preview.evidence_sources.find((value) => value.chunk_id === citation);
            return <p key={citation}>{source ? `${source.relative_path} · ${source.anchor_value}` : citation}</p>;
          })}
        </details>
      </article>)}
    </>}
  </section>;
}
