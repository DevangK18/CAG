import React from 'react';

interface DiagramCardProps {
    title?: string;
    children: React.ReactNode;
}

export const DiagramCard: React.FC<DiagramCardProps> = ({ title, children }) => {
    return (
        <div className="diagram-card">
            {title && <h3 className="diagram-card-title">{title}</h3>}
            <div className="diagram-card-content">{children}</div>
        </div>
    );
};
