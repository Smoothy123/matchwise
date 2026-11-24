/**
 * The agent's replies are plain text with a little markdown: "* " bullets, "1. " lists, **bold**,
 * and job references like [#5083]. This turns exactly those into elements and everything else into
 * text. Nothing is ever set as HTML: the reply comes from an LLM, so it's untrusted input, and
 * React escapes text, so "<script>" in a reply shows up as those characters and nothing more.
 */
import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router';

type Block =
  { kind: 'paragraph'; lines: string[] } | { kind: 'bullets' | 'numbers'; items: string[] };

const BULLET = /^\s*[*-]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const line of text.split('\n')) {
    const last = blocks.at(-1);
    const kind = BULLET.test(line) ? 'bullets' : NUMBER.test(line) ? 'numbers' : null;
    if (kind) {
      const item = line.replace(kind === 'bullets' ? BULLET : NUMBER, '');
      if (last?.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else if (line.trim() === '') {
      blocks.push({ kind: 'paragraph', lines: [] }); // a blank line ends whatever came before
    } else if (last?.kind === 'paragraph') {
      last.lines.push(line);
    } else {
      blocks.push({ kind: 'paragraph', lines: [line] });
    }
  }
  return blocks.filter((block) => block.kind !== 'paragraph' || block.lines.length > 0);
}

const INLINE = /(\*\*[^*\n]+\*\*|\[#\d{1,15}\])/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const job = /^\[#(\d+)\]$/.exec(part);
    if (job?.[1]) {
      return (
        // The name keeps the visible "#5083", so voice control ("click #5083") still works.
        <Link
          key={i}
          to={{ search: `?job=${job[1]}` }}
          state={{ fromList: true }}
          aria-label={`Details for job #${job[1]}`}
        >
          #{job[1]}
        </Link>
      );
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

export function ReplyText({ text }: { text: string }) {
  return (
    <>
      {parseBlocks(text).map((block, i) => {
        if (block.kind === 'paragraph') {
          return (
            <p key={i}>
              {block.lines.map((line, j) => (
                <Fragment key={j}>
                  {j > 0 ? <br /> : null}
                  {inline(line)}
                </Fragment>
              ))}
            </p>
          );
        }
        const items = block.items.map((item, j) => <li key={j}>{inline(item)}</li>);
        return block.kind === 'bullets' ? <ul key={i}>{items}</ul> : <ol key={i}>{items}</ol>;
      })}
    </>
  );
}
