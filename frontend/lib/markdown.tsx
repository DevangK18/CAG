/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Simple Markdown renderer for summaries
 * Extracted from index.tsx for better code organization
 */

import React from 'react';

/**
 * Renders inline formatting (bold, italic) within text
 */
const renderInlineFormatting = (text: string): React.ReactNode => {
  const result: React.ReactNode[] = [];
  const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__)/g);

  parts.forEach((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      result.push(<strong key={i}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith('__') && part.endsWith('__')) {
      result.push(<strong key={i}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      result.push(<em key={i}>{part.slice(1, -1)}</em>);
    } else {
      result.push(part);
    }
  });

  return result;
};

/**
 * Renders markdown content to React elements
 * Supports: headers, lists, blockquotes, bold, italic, horizontal rules
 */
export const renderMarkdown = (content: string): React.ReactNode => {
  if (!content) return null;

  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let currentList: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let key = 0;

  const flushList = () => {
    if (currentList.length > 0) {
      if (listType === 'ol') {
        elements.push(
          <ol key={key++} className="summary-list ordered">
            {currentList.map((item, i) => <li key={i}>{renderInlineFormatting(item)}</li>)}
          </ol>
        );
      } else {
        elements.push(
          <ul key={key++} className="summary-list">
            {currentList.map((item, i) => <li key={i}>{renderInlineFormatting(item)}</li>)}
          </ul>
        );
      }
      currentList = [];
      listType = null;
    }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();

    // Headers
    if (trimmed.startsWith('# ')) {
      flushList();
      elements.push(<h1 key={key++} className="summary-h1">{trimmed.slice(2)}</h1>);
    } else if (trimmed.startsWith('## ')) {
      flushList();
      elements.push(<h2 key={key++} className="summary-h2">{trimmed.slice(3)}</h2>);
    } else if (trimmed.startsWith('### ')) {
      flushList();
      elements.push(<h3 key={key++} className="summary-h3">{trimmed.slice(4)}</h3>);
    } else if (trimmed.startsWith('#### ')) {
      flushList();
      elements.push(<h4 key={key++} className="summary-h4">{trimmed.slice(5)}</h4>);
    }
    // Horizontal rule
    else if (trimmed === '---' || trimmed === '***') {
      flushList();
      elements.push(<hr key={key++} className="summary-hr" />);
    }
    // Ordered list
    else if (/^\d+\.\s/.test(trimmed)) {
      if (listType !== 'ol') {
        flushList();
        listType = 'ol';
      }
      currentList.push(trimmed.replace(/^\d+\.\s/, ''));
    }
    // Unordered list
    else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || trimmed.startsWith('• ')) {
      if (listType !== 'ul') {
        flushList();
        listType = 'ul';
      }
      currentList.push(trimmed.slice(2));
    }
    // Blockquote
    else if (trimmed.startsWith('> ')) {
      flushList();
      elements.push(<blockquote key={key++} className="summary-blockquote">{renderInlineFormatting(trimmed.slice(2))}</blockquote>);
    }
    // Empty line
    else if (trimmed === '') {
      flushList();
    }
    // Regular paragraph
    else {
      flushList();
      elements.push(<p key={key++} className="summary-paragraph">{renderInlineFormatting(trimmed)}</p>);
    }
  });

  flushList();
  return elements;
};
