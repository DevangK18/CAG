/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * ChatMessage Component
 * Renders chat messages with clickable citations AND markdown formatting
 *
 * v5.2: Fixed loading animation + simplified streaming approach
 */

import React, { useMemo, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { useAppStore } from '../stores/appStore';
import { lookupCitation } from '../lib/citationUtils';

interface ChatMessageProps {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isWaitingForResponse?: boolean;
}

// =============================================================================
// Loading animation messages - expanded & will be shuffled
// =============================================================================

const LOADING_MESSAGES = [
  // Technical/analytical
  'Analyzing',
  'Processing',
  'Examining',
  'Investigating',
  'Parsing',
  'Computing',
  'Evaluating',
  'Assessing',
  // Thoughtful
  'Thinking',
  'Reasoning',
  'Pondering',
  'Contemplating',
  'Considering',
  'Reflecting',
  'Deliberating',
  'Meditating',
  // Creative/fun (Claude Code style)
  'Philosophizing',
  'Synthesizing',
  'Galvanizing',
  'Orchestrating',
  'Crystallizing',
  'Illuminating',
  'Deciphering',
  'Unraveling',
  // Domain-specific (audit context)
  'Auditing',
  'Verifying',
  'Cross-referencing',
  'Correlating',
  'Aggregating',
  'Summarizing',
  'Extracting',
  'Reconciling',
];

// Fisher-Yates shuffle
function shuffleArray<T>(array: T[]): T[] {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

// =============================================================================
// STEP 1: Normalize markdown (insert missing newlines)
// =============================================================================

function normalizeMarkdownContent(content: string): string {
  if (!content || content.length < 10) return content;

  let result = content;

  // 1) Insert \n\n BEFORE heading markers (### etc.)
  result = result.replace(/([^\n])\s*(#{1,6}\s)/g, '$1\n\n$2');

  // 2) Insert \n\n BEFORE bold list items: "- **Something**"
  result = result.replace(/([^\n])\s+(- \*\*)/g, '$1\n\n- **');

  // 3) Insert \n\n BEFORE plain list items: "- Capital letter"
  result = result.replace(/([^\n\-])\s+(- [A-Z])/g, '$1\n\n$2');

  // 4) Insert \n before table rows (| col | col |)
  result = result.replace(/([^\n|])\s*(\|[^|\n]+\|)/g, '$1\n$2');

  // 5) Separate heading text from body text
  result = result.replace(
    /(#{1,6}\s+(?:[A-Z][a-z&]*(?:\s+[A-Z][a-z&]*){0,4}))\s+((?:The|A|An|This|In|During|SAIL|NLC|CAG|FRBM|As|For|Under|Overall|Immediate|Management|According|Bokaro|Bhilai|Rourkela|Durgapur|IISCO|Revenue|Audit|These|While|Furthermore)\s)/g,
    '$1\n\n$2'
  );

  // 6) Collapse 3+ newlines into exactly 2
  result = result.replace(/\n{3,}/g, '\n\n');

  return result.trim();
}

// =============================================================================
// STEP 2: Convert citations to HTML spans (for rehype-raw)
// =============================================================================

function preprocessCitations(content: string): string {
  return content.replace(
    /\[([^\]]*(?:p\.?\s*\d+|page\s*\d+)[^\]]*)\]/gi,
    (match, citationText) => {
      return `<span class="citation-badge" data-citation="${citationText.trim()}">${match}</span>`;
    }
  );
}

// =============================================================================
// STEP 2.5: Shorten citation display text
// =============================================================================

function shortenCitationLabel(raw: string): string {
  const text = raw.replace(/^\[|\]$/g, '');
  const pageMatch = text.match(/^(.*),\s*(p\.\s*\d+)$/);
  if (!pageMatch) return text;

  const section = pageMatch[1];
  const page = pageMatch[2];

  if (section.length <= 30) return `${section}, ${page}`;
  return `${section.substring(0, 27)}..., ${page}`;
}

// =============================================================================
// STEP 3: ReactMarkdown component overrides
// =============================================================================

const createMarkdownComponents = (
  normalizedCitationMap: Map<string, any>,
  navigateToCitation: (citation: any) => void
) => ({
  h1: ({ children, ...props }: any) => (
    <h1 className="text-xl font-bold text-gray-900 mt-5 mb-2 pb-1 border-b border-gray-200" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: any) => (
    <h2 className="text-lg font-bold text-gray-900 mt-5 mb-2 pb-1 border-b border-gray-100" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }: any) => (
    <h3 className="text-base font-semibold text-gray-900 mt-4 mb-1.5" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, ...props }: any) => (
    <h4 className="text-sm font-semibold text-gray-800 mt-3 mb-1" {...props}>
      {children}
    </h4>
  ),
  p: ({ children, ...props }: any) => (
    <p className="mb-2.5 leading-relaxed text-gray-700 text-sm" {...props}>
      {children}
    </p>
  ),
  strong: ({ children, ...props }: any) => (
    <strong className="font-semibold text-gray-900" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }: any) => (
    <em className="italic text-gray-600" {...props}>
      {children}
    </em>
  ),
  ul: ({ children, ...props }: any) => (
    <ul className="list-disc ml-5 mb-3 space-y-1 text-sm text-gray-700" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: any) => (
    <ol className="list-decimal ml-5 mb-3 space-y-1 text-sm text-gray-700" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }: any) => (
    <li className="leading-relaxed" {...props}>
      {children}
    </li>
  ),
  table: ({ children, ...props }: any) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-gray-200">
      <table className="min-w-full text-sm" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }: any) => (
    <thead className="bg-gray-50" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, ...props }: any) => (
    <th className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-gray-200" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }: any) => (
    <td className="px-3 py-2 text-gray-600 border-b border-gray-100" {...props}>
      {children}
    </td>
  ),
  blockquote: ({ children, ...props }: any) => (
    <blockquote className="border-l-4 border-blue-300 pl-3 my-3 text-gray-600 italic text-sm" {...props}>
      {children}
    </blockquote>
  ),
  code: ({ children, className, ...props }: any) => {
    const isBlock = className?.includes('language-');
    if (isBlock) {
      return (
        <pre className="bg-gray-900 text-gray-100 rounded-lg p-3 my-3 overflow-x-auto text-xs">
          <code className={className} {...props}>
            {children}
          </code>
        </pre>
      );
    }
    return (
      <code className="bg-gray-100 text-gray-800 px-1.5 py-0.5 rounded text-xs font-mono" {...props}>
        {children}
      </code>
    );
  },
  hr: () => <hr className="my-4 border-gray-200" />,
  a: ({ children, href, ...props }: any) => (
    <a
      href={href}
      className="text-blue-600 hover:text-blue-800 underline"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    >
      {children}
    </a>
  ),
  span: ({ children, className, ...props }: any) => {
    if (className === 'citation-badge') {
      const citationText = props['data-citation'] as string;

      if (!citationText) {
        return <span className={className} {...props}>{children}</span>;
      }

      const citation = lookupCitation(citationText, normalizedCitationMap);
      const displayText = shortenCitationLabel(citationText);
      const fullText = citationText;

      if (citation) {
        return (
          <button
            className="inline-flex items-center px-2 py-0.5 mx-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 cursor-pointer hover:bg-blue-100 transition-colors"
            onClick={() => navigateToCitation(citation)}
            title={`${fullText}\nClick to view in PDF`}
          >
            [{displayText}]
          </button>
        );
      } else {
        return (
          <span
            className="inline-flex items-center px-2 py-0.5 mx-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600 border border-gray-300"
            title={fullText}
          >
            [{displayText}]
          </span>
        );
      }
    }
    return <span className={className} {...props}>{children}</span>;
  },
});

// =============================================================================
// Loading Animation Component
// =============================================================================

function LoadingAnimation() {
  const [shuffledMessages] = useState(() => shuffleArray(LOADING_MESSAGES));
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      setIsExiting(true);
      setTimeout(() => {
        setCurrentIndex((prev) => (prev + 1) % shuffledMessages.length);
        setIsExiting(false);
      }, 150); // Quick exit animation
    }, 1200); // Change word every 1.2s

    return () => clearInterval(interval);
  }, [shuffledMessages.length]);

  return (
    <div className="thinking-animation">
      <div className="thinking-indicator">
        <span className="thinking-dot"></span>
        <span className="thinking-dot"></span>
        <span className="thinking-dot"></span>
      </div>
      <span className={`thinking-text ${isExiting ? 'exiting' : 'entering'}`}>
        {shuffledMessages[currentIndex]}
      </span>
    </div>
  );
}

// =============================================================================
// COMPONENT
// =============================================================================

export function ChatMessage({ role, content, isStreaming, isWaitingForResponse }: ChatMessageProps) {
  const { normalizedCitationMap, navigateToCitation } = useAppStore();

  const markdownComponents = useMemo(
    () => createMarkdownComponents(normalizedCitationMap, navigateToCitation),
    [normalizedCitationMap, navigateToCitation]
  );

  if (role === 'user') {
    return (
      <div className="chat-message user">
        <div className="message-avatar">You</div>
        <div className="message-content">
          {content}
        </div>
      </div>
    );
  }

  // =========================================================================
  // ASSISTANT MESSAGE — loading or markdown rendering
  // =========================================================================

  // Show loading animation if waiting for first token
  if (isWaitingForResponse) {
    return (
      <div className="chat-message assistant">
        <div className="message-avatar">AI</div>
        <div className="message-content ai-message-content">
          <LoadingAnimation />
        </div>
      </div>
    );
  }

  // Render markdown content (use content directly - no separate displayedContent)
  const normalizedContent = normalizeMarkdownContent(content);
  const processedContent = preprocessCitations(normalizedContent);

  return (
    <div className="chat-message assistant">
      <div className="message-avatar">AI</div>
      <div className={`message-content ai-message-content ${isStreaming ? 'streaming' : ''}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={markdownComponents}
        >
          {processedContent}
        </ReactMarkdown>
        {isStreaming && <span className="streaming-cursor" />}
      </div>
    </div>
  );
}

export default ChatMessage;
