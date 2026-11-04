'use strict';

function outputToText(output) {
  if (typeof output === 'string') return output;
  if (Array.isArray(output)) {
    return output
      .map((part) => (part && typeof part === 'object' ? part.text : String(part ?? '')))
      .filter((s) => s.length > 0)
      .join('\n');
  }
  if (output && typeof output === 'object') {
    if (typeof output.text === 'string') return output.text;
    try {
      return JSON.stringify(output);
    } catch (_) {
      return String(output);
    }
  }
  return String(output ?? '');
}

/**
 * Mutates a parsed Responses request body. Returns the number of synthetic
 * function_call_output items that were rewritten into user messages.
 */
function rewriteBody(obj) {
  let changed = 0;
  if (!obj || !Array.isArray(obj.input)) return changed;

  const out = [];
  for (const item of obj.input) {
    const isSyntheticOutput =
      item &&
      typeof item === 'object' &&
      item.type === 'function_call_output' &&
      (item.call_id === undefined || item.call_id === null || item.call_id === '');

    if (!isSyntheticOutput) {
      out.push(item);
      continue;
    }

    changed += 1;
    const nsName = item.namespace ? `${item.namespace}.` : '';
    const toolName = item.name ? `${nsName}${item.name}` : 'codex_app';
    const text = outputToText(item.output);
    out.push({
      type: 'message',
      role: 'user',
      content: [
        {
          type: 'input_text',
          text: `[Delegated task delivered by ${toolName}]\n${text}`,
        },
      ],
    });
  }

  obj.input = out;
  return changed;
}

module.exports = { outputToText, rewriteBody };
