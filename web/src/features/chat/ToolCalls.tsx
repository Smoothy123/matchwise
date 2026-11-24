import styles from './Chat.module.css';
import { describeArguments, toolLabel, type ToolUse } from './turns';

/** A collapsed "tools used" line above a reply. <details> gives the toggle, keyboard support
 * and the expanded/collapsed state for screen readers, with no JavaScript. */
export function ToolCalls({ tools }: { tools: ToolUse[] }) {
  if (tools.length === 0) return null;
  const failures = tools.filter((tool) => !tool.ok).length;
  return (
    <details className={styles.tools}>
      <summary>
        {tools.length === 1 ? 'Used 1 tool' : `Used ${String(tools.length)} tools`}:{' '}
        {tools.map((tool) => tool.name).join(', ')}
        {failures > 0 ? ` (${String(failures)} failed)` : ''}
      </summary>
      <ol className={styles.toolList}>
        {tools.map((tool, i) => (
          <li key={i}>
            <p className={styles.toolHead}>
              <code>{tool.name}</code> {toolLabel(tool.name)}{' '}
              <span className={tool.ok ? styles.toolOk : styles.toolFailed}>
                <span aria-hidden="true">{tool.ok ? '✓' : '✗'}</span>{' '}
                {tool.ok ? 'worked' : 'failed'}
              </span>
            </p>
            {describeArguments(tool.arguments).map((argument) => (
              <p key={argument} className={styles.toolArgument}>
                {argument}
              </p>
            ))}
          </li>
        ))}
      </ol>
    </details>
  );
}
