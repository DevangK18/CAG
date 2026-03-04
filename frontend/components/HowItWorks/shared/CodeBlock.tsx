import React from 'react';

interface CodeBlockProps {
    children: React.ReactNode;
    title?: string;
}

export const CodeBlock: React.FC<CodeBlockProps> = ({ children, title }) => {
    return (
        <div className="code-block-wrapper">
            {title && <div className="code-block-title">{title}</div>}
            <pre className="code-block">{children}</pre>
        </div>
    );
};
