import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

interface MermaidDiagramProps {
    chart: string;
    caption?: string;
}

// Initialize mermaid with light theme
mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    themeVariables: {
        primaryColor: '#1a365d',
        primaryTextColor: '#1e293b',
        primaryBorderColor: '#1a365d',
        lineColor: '#64748b',
        secondaryColor: '#e0f2fe',
        tertiaryColor: '#f1f5f9',
        background: '#ffffff',
        mainBkg: '#ffffff',
        secondBkg: '#f8fafc',
        border1: '#cbd5e1',
        border2: '#94a3b8',
        fontSize: '14px',
        fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    },
});

export const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ chart, caption }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const renderDiagram = async () => {
            if (!containerRef.current || !chart) return;

            try {
                setIsLoading(true);
                setError(null);

                // Generate unique ID for this diagram
                const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;

                // Render the diagram
                const { svg } = await mermaid.render(id, chart);

                // Insert the SVG into the container
                if (containerRef.current) {
                    containerRef.current.innerHTML = svg;
                }

                setIsLoading(false);
            } catch (err) {
                console.error('Mermaid rendering error:', err);
                setError('Failed to render diagram');
                setIsLoading(false);
            }
        };

        renderDiagram();
    }, [chart]);

    return (
        <div className="mermaid-diagram-wrapper">
            {isLoading && (
                <div className="mermaid-loading">
                    <div className="spinner"></div>
                    <span>Rendering diagram...</span>
                </div>
            )}
            {error && (
                <div className="mermaid-error">
                    <span>⚠️ {error}</span>
                </div>
            )}
            <div ref={containerRef} className="mermaid-diagram" style={{ display: isLoading || error ? 'none' : 'block' }} />
            {caption && !error && !isLoading && (
                <p className="diagram-caption">{caption}</p>
            )}
        </div>
    );
};
