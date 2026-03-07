import React, { useState } from 'react';

interface PromptTab {
    label: string;
    subtitle?: string;
    content: string;
    color?: string;
    meta?: string;
}

interface TabbedPromptProps {
    title: string;
    description?: string;
    tabs: PromptTab[];
    maxHeight?: number;
}

export const TabbedPrompt: React.FC<TabbedPromptProps> = ({
    title,
    description,
    tabs,
    maxHeight = 480,
}) => {
    const [activeIndex, setActiveIndex] = useState(0);
    const activeTab = tabs[activeIndex];
    const activeColor = activeTab?.color || '#1a365d';

    return (
        <div style={{
            border: '1px solid #e2e8f0',
            borderRadius: '12px',
            overflow: 'hidden',
            margin: '20px 0',
            background: '#ffffff',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04)',
        }}>
            <div style={{
                padding: '16px 22px 0 22px',
                background: '#f8fafc',
                borderBottom: '1px solid #e2e8f0',
            }}>
                <div style={{
                    fontSize: '15px',
                    fontWeight: 700,
                    color: '#1e293b',
                    marginBottom: description ? '4px' : '14px',
                    letterSpacing: '-0.01em',
                }}>
                    {title}
                </div>
                {description && (
                    <div style={{
                        fontSize: '13px',
                        color: '#64748b',
                        marginBottom: '14px',
                        lineHeight: 1.5,
                    }}>
                        {description}
                    </div>
                )}
                <div style={{
                    display: 'flex',
                    gap: '0',
                    overflowX: 'auto',
                    scrollbarWidth: 'none',
                    msOverflowStyle: 'none',
                    WebkitOverflowScrolling: 'touch',
                } as React.CSSProperties}>
                    {tabs.map((tab, index) => {
                        const isActive = index === activeIndex;
                        const tabColor = tab.color || '#1a365d';
                        return (
                            <button
                                key={`${tab.label}-${index}`}
                                onClick={() => setActiveIndex(index)}
                                style={{
                                    padding: '9px 16px',
                                    fontSize: '13px',
                                    fontWeight: isActive ? 700 : 500,
                                    color: isActive ? tabColor : '#64748b',
                                    background: 'none',
                                    border: 'none',
                                    borderBottom: isActive
                                        ? `2.5px solid ${tabColor}`
                                        : '2.5px solid transparent',
                                    cursor: 'pointer',
                                    whiteSpace: 'nowrap',
                                    transition: 'color 0.15s ease, border-color 0.15s ease',
                                    marginBottom: '-1px',
                                    flexShrink: 0,
                                }}
                            >
                                {tab.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {activeTab?.subtitle && (
                <div style={{
                    padding: '10px 22px',
                    fontSize: '13px',
                    color: '#475569',
                    background: '#f8fafc',
                    borderBottom: '1px solid #f1f5f9',
                    lineHeight: 1.5,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                }}>
                    <span style={{
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: activeColor,
                        flexShrink: 0,
                    }} />
                    {activeTab.subtitle}
                </div>
            )}

            <div style={{
                maxHeight: `${maxHeight}px`,
                overflowY: 'auto',
                background: '#1e293b',
            }}>
                <pre style={{
                    margin: 0,
                    padding: '20px 22px',
                    fontSize: '12.5px',
                    lineHeight: 1.7,
                    color: '#e2e8f0',
                    fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', Consolas, monospace",
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    tabSize: 2,
                }}>
                    {activeTab?.content || ''}
                </pre>
            </div>

            <div style={{
                padding: '9px 22px',
                background: '#f8fafc',
                borderTop: '1px solid #e2e8f0',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: '12px',
                color: '#94a3b8',
            }}>
                <span>{activeTab?.meta || activeTab?.label}</span>
                <span>{activeTab?.content.split('\n').length} lines</span>
            </div>
        </div>
    );
};