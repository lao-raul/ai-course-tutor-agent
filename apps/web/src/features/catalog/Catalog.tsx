import { useEffect, useMemo, useState } from 'react';
import { practiceApi } from '../../api/practice';
import type { Book, Category, SearchFilters } from '../../api/practice';
import type { Labels } from '../../i18n';

interface Props { labels: Labels; onOpen: (bookId: string) => void }

export function Catalog({ labels, onOpen }: Props) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [query, setQuery] = useState('');
  const [books, setBooks] = useState<Book[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { practiceApi.categories().then(setCategories).catch(() => setCategories([])); }, []);
  useEffect(() => {
    let active = true;
    practiceApi.books(filters).then((page) => {
      if (active) { setBooks(page.items); setCursor(page.next_cursor); setError(''); }
    }).catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters]);

  const choices = useMemo(() => (type: Category['category_type']) =>
    categories.filter((item) => item.category_type === type && item.book_count > 0), [categories]);
  const update = (key: keyof SearchFilters, value: string) => {
    setLoading(true);
    setBooks([]);
    setCursor(null);
    setFilters((previous) => ({ ...previous, [key]: value || undefined, cursor: undefined }));
  };
  const loadMore = async () => {
    if (!cursor || loading) return;
    setLoading(true);
    try {
      const page = await practiceApi.books({ ...filters, cursor });
      setBooks((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor);
      setError('');
    } catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  };

  return <section aria-label={labels.discover}>
    <h2>{labels.discover}</h2>
    <form className="hiruzen-search" onSubmit={(event) => { event.preventDefault(); update('q', query.trim()); }}>
      <label>{labels.search}
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={labels.searchHint} />
      </label>
      <button type="submit">{labels.search}</button>
    </form>
    <div className="hiruzen-filters">
      {(['education_level', 'grade', 'subject', 'publisher'] as const).map((field) =>
        <label key={field}>{field === 'education_level' ? labels.level : labels[field]}
          <select value={filters[field] ?? ''} onChange={(event) => update(field, event.target.value)}>
            <option value="">{labels.all}</option>
            {choices(field).map((item) => <option key={item.id} value={field === 'education_level' ? item.stable_key.replace(/^education:/, '') : item.display_name}>{item.display_name} ({item.book_count})</option>)}
          </select>
        </label>,
      )}
    </div>
    {error && <p role="alert" className="hiruzen-error">{labels.error}: {error} <button onClick={() => setFilters({ ...filters })}>{labels.retry}</button></p>}
    {loading && <p role="status">{labels.loading}</p>}
    {!loading && !error && books.length === 0 && <p>{labels.noBooks}</p>}
    <ul className="hiruzen-books">
      {books.map((book) => <li key={book.id}>
        <h3>{book.title}</h3>
        <p>{book.education_level} · {book.grade} · {book.subject} · {book.publisher} · {book.term}</p>
        <button type="button" onClick={() => onOpen(book.id)}>{labels.open}</button>
      </li>)}
    </ul>
    {cursor && <button type="button" disabled={loading} onClick={loadMore}>{labels.more}</button>}
  </section>;
}
