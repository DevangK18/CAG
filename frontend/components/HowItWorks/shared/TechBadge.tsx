import React from 'react';

interface TechBadgeProps {
    name: string;
    category?: 'language' | 'backend' | 'frontend' | 'ai' | 'database' | 'parsing' | 'infrastructure' | 'other';
}

const categoryColors: Record<string, { bg: string; text: string; border: string }> = {
    language: { bg: '#fef3c7', text: '#92400e', border: '#fbbf24' },
    backend: { bg: '#dbeafe', text: '#1e40af', border: '#1a365d' },
    frontend: { bg: '#e0e7ff', text: '#3730a3', border: '#6366f1' },
    ai: { bg: '#fae8ff', text: '#701a75', border: '#d946ef' },
    database: { bg: '#dcfce7', text: '#166534', border: '#22c55e' },
    parsing: { bg: '#ffedd5', text: '#9a3412', border: '#fb923c' },
    infrastructure: { bg: '#f3f4f6', text: '#374151', border: '#9ca3af' },
    other: { bg: '#f1f5f9', text: '#475569', border: '#cbd5e1' },
};

export const TechBadge: React.FC<TechBadgeProps> = ({ name, category = 'other' }) => {
    const colors = categoryColors[category] || categoryColors.other;

    return (
        <span
            className="tech-badge"
            style={{
                backgroundColor: colors.bg,
                color: colors.text,
                border: `1px solid ${colors.border}`,
                padding: '6px 12px',
                borderRadius: '6px',
                fontSize: '13px',
                fontWeight: 500,
                display: 'inline-block',
                margin: '4px',
            }}
        >
            {name}
        </span>
    );
};
