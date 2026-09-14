import type { CSSProperties } from 'react';
import Markdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import 'katex/dist/katex.min.css';
import './RichText.css';

interface RichTextProps {
  text: string;
}

/** Render model-authored Markdown and TeX without enabling raw HTML. */
export function RichText({ text }: RichTextProps) {
  return (
    <div className="course-rich-text" style={styles.root}>
      <Markdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          [
            rehypeKatex,
            {
              // KaTeX's default matrix spacing is too tight for stacked fractions.
              macros: { '\\arraystretch': '1.6' },
            },
          ],
        ]}
        skipHtml
        components={{
          p: ({ children }) => <p style={styles.paragraph}>{children}</p>,
          ul: ({ children }) => <ul style={styles.list}>{children}</ul>,
          ol: ({ children }) => <ol style={styles.list}>{children}</ol>,
          code: ({ children, className }) => (
            <code className={className} style={styles.code}>
              {children}
            </code>
          ),
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  root: {
    color: '#111827',
    fontSize: '15px',
    lineHeight: 1.6,
    overflowWrap: 'anywhere',
  },
  paragraph: {
    margin: '0 0 0.65em',
  },
  list: {
    margin: '0 0 0.65em',
    paddingLeft: '1.5em',
  },
  code: {
    backgroundColor: '#f3f4f6',
    borderRadius: '3px',
    padding: '0.1em 0.25em',
  },
};
