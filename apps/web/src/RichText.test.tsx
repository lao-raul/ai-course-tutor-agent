import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { RichText } from './RichText';

describe('RichText', () => {
  it('renders Markdown lists and inline TeX instead of exposing delimiters', () => {
    const html = renderToStaticMarkup(
      <RichText text={'**Row View** uses $A$ and $x$.\n\n- First equation\n- Second equation'} />,
    );

    expect(html).toContain('<strong>Row View</strong>');
    expect(html).toContain('class="katex"');
    expect(html).toContain('<li>First equation</li>');
    expect(html).not.toContain('$A$');
  });

  it('does not render model-authored raw HTML', () => {
    const html = renderToStaticMarkup(
      <RichText text={'Safe text <img src="x" onerror="window.alert(\'unsafe\')">'} />,
    );

    expect(html).toContain('Safe text');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('window.alert');
  });

  it('adds enough row spacing for matrices containing stacked fractions', () => {
    const matrix = String.raw`$$
H = \begin{bmatrix}
\frac{\partial^2 f}{\partial x_1^2} & \frac{\partial^2 f}{\partial x_1 \partial x_2} \\
\frac{\partial^2 f}{\partial x_2 \partial x_1} & \frac{\partial^2 f}{\partial x_2^2}
\end{bmatrix}
$$`;
    const html = renderToStaticMarkup(<RichText text={matrix} />);
    const verticalList = html.match(/style="height:([0-9.]+)em;vertical-align:/);

    expect(html).toContain('class="katex-display"');
    expect(verticalList).not.toBeNull();
    expect(Number(verticalList?.[1])).toBeGreaterThan(3.5);
  });
});
