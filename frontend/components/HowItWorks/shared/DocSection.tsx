import React from 'react';

interface DocSectionProps {
    title: string;
    description?: string;
    children: React.ReactNode;
}

export const DocSection: React.FC<DocSectionProps> = ({ title, description, children }) => {
    return (
        <section className="doc-section">
            <h2 className="doc-section-title">{title}</h2>
            {description && <p className="doc-section-description">{description}</p>}
            <div className="doc-section-content">{children}</div>
        </section>
    );
};
