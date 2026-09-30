import React from "react";

// Minimal, dependency-free highlighter for JavaScript/TypeScript and Python snippets.
// Output is React text nodes inside spans (never innerHTML), so indexed source cannot inject markup.
const JS_KEYWORDS = new Set("async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield abstract as declare enum implements interface keyof namespace private protected public readonly type".split(" "));
const PY_KEYWORDS = new Set("and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return self True try while with yield".split(" "));

const JS_TOKEN = /(\/\/.*$)|(\/\*.*?(?:\*\/|$))|("(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?|`(?:\\.|[^`\\])*`?)|(\b\d[\d_]*(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)/g;
const PY_TOKEN = /(#.*$)|()("""|'''|"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?)|(\b\d[\d_]*(?:\.\d+)?\b)|([A-Za-z_][\w]*)/g;

type State = { inBlockComment: boolean };

function highlightLine(line: string, python: boolean, state: State): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let rest = line, offset = 0;
  if (!python && state.inBlockComment) {
    const end = line.indexOf("*/");
    const upto = end === -1 ? line.length : end + 2;
    out.push(<span key="bc" className="tok-comment">{line.slice(0, upto)}</span>);
    state.inBlockComment = end === -1;
    rest = line.slice(upto); offset = upto;
    if (state.inBlockComment) return out;
  }
  const re = new RegExp((python ? PY_TOKEN : JS_TOKEN).source, "g");
  let last = 0, match: RegExpExecArray | null, key = 0;
  const keywords = python ? PY_KEYWORDS : JS_KEYWORDS;
  while ((match = re.exec(rest)) !== null) {
    if (match[0] === "") { re.lastIndex++; continue; }
    if (match.index > last) out.push(rest.slice(last, match.index));
    const [text, lineComment, blockComment, str, num, word] = match;
    let cls = "";
    if (lineComment) cls = "tok-comment";
    else if (blockComment) { cls = "tok-comment"; if (!blockComment.endsWith("*/")) state.inBlockComment = true; }
    else if (str) cls = "tok-string";
    else if (num) cls = "tok-number";
    else if (word) {
      if (keywords.has(word)) cls = "tok-keyword";
      else if (rest.slice(re.lastIndex).trimStart().startsWith("(")) cls = "tok-call";
    }
    out.push(cls ? <span key={`${offset}-${key++}`} className={cls}>{text}</span> : text);
    last = re.lastIndex;
  }
  if (last < rest.length) out.push(rest.slice(last));
  return out;
}

export function highlightLines(text: string, language: string): React.ReactNode[][] {
  const python = language.toLowerCase() === "python";
  const state: State = { inBlockComment: false };
  return text.split("\n").map((line) => highlightLine(line, python, state));
}
