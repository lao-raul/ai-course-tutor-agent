import type { Language } from '../../api/practice';
import type { Labels } from '../../i18n';

export function LanguageSelector({ language, onChange, labels }: { language: Language; onChange: (value: Language) => void; labels: Labels }) {
  return <label className="hiruzen-language">{labels.language}
    <select value={language} onChange={(event) => onChange(event.target.value as Language)}>
      <option value="zh">中文</option>
      <option value="en">English</option>
      <option value="bilingual">中文 / English</option>
    </select>
  </label>;
}
