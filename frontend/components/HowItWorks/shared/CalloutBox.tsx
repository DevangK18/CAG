import React from 'react';

interface CalloutBoxProps {
    type?: 'info' | 'warning' | 'success' | 'note';
    children: React.ReactNode;
}

const calloutStyles: Record<string, { bg: string; border: string; icon: string }> = {
    info: { bg: '#eff6ff', border: '#3b82f6', icon: 'ℹ️' },
    warning: { bg: '#fef3c7', border: '#f59e0b', icon: '⚠️' },
    success: { bg: '#d1fae5', border: '#10b981', icon: '✓' },
    note: { bg: '#f3f4f6', border: '#6b7280', icon: '📝' },
};

export const CalloutBox: React.FC<CalloutBoxProps> = ({ type = 'info', children }) => {
    const style = calloutStyles[type];

    return (
        <div
            className="callout-box"
            style={{
                backgroundColor: style.bg,
                borderLeft: `4px solid ${style.border}`,
                padding: '16px',
                borderRadius: '8px',
                margin: '16px 0',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                <span style={{ fontSize: '20px', lineHeight: 1 }}>{style.icon}</span>
                <div style={{ flex: 1, fontSize: '14px', lineHeight: '1.6', color: '#374151' }}>
                    {children}
                </div>
            </div>
        </div>
    );
};
