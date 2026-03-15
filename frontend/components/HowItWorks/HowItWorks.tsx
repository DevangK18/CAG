import React, { useState } from 'react';
import { Overview } from './tabs/Overview';
import { DataPipeline } from './tabs/DataPipeline';
import { RAGSearch } from './tabs/RAGSearch';
import { AIFeatures } from './tabs/AIFeatures';
import { FrontendArchitecture } from './tabs/FrontendArchitecture';
import { Infrastructure } from './tabs/Infrastructure';

type TabId = 'overview' | 'data-pipeline' | 'rag-search' | 'ai-features' | 'frontend' | 'infrastructure';

interface Tab {
    id: TabId;
    label: string;
}

const tabs: Tab[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'data-pipeline', label: 'Data Pipeline' },
    { id: 'rag-search', label: 'RAG & Search' },
    { id: 'ai-features', label: 'AI Features' },
    { id: 'frontend', label: 'Frontend' },
    { id: 'infrastructure', label: 'Infrastructure' },
];

// Tabs that are under development
const underDevelopmentTabs: TabId[] = ['frontend', 'infrastructure'];

const UnderDevelopmentOverlay: React.FC = () => (
    <div className="under-development-overlay">
        <div className="under-development-content">
            <div className="under-development-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
            </div>
            <h2 className="under-development-title">Under Construction</h2>
            <p className="under-development-message">
                This section is being updated and doesn't reflect the current state of the project.
            </p>
            <div className="under-development-suggestion">
                <span>Check out the live sections:</span>
                <div className="available-tabs">
                    <span className="available-tab">Data Pipeline</span>
                    <span className="available-tab">RAG & Search</span>
                    <span className="available-tab">AI Features</span>
                </div>
            </div>
        </div>
    </div>
);

export const HowItWorks: React.FC = () => {
    const [activeTab, setActiveTab] = useState<TabId>('data-pipeline');

    const isUnderDevelopment = underDevelopmentTabs.includes(activeTab);

    const renderTabContent = () => {
        switch (activeTab) {
            case 'overview':
                return <Overview />;
            case 'data-pipeline':
                return <DataPipeline />;
            case 'rag-search':
                return <RAGSearch />;
            case 'ai-features':
                return <AIFeatures />;
            case 'frontend':
                return <FrontendArchitecture />;
            case 'infrastructure':
                return <Infrastructure />;
            default:
                return <Overview />;
        }
    };

    return (
        <div className="how-it-works-container">
            {/* Horizontal Tab Bar */}
            <div className="how-it-works-tabs">
                <div className="tabs-inner">
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            className={`tab-button ${activeTab === tab.id ? 'active' : ''} ${underDevelopmentTabs.includes(tab.id) ? 'tab-wip' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            {tab.label}
                            {underDevelopmentTabs.includes(tab.id) && <span className="wip-badge">WIP</span>}
                        </button>
                    ))}
                </div>
            </div>

            {/* Tab Content */}
            <div className="how-it-works-content">
                <div className="content-wrapper">
                    {isUnderDevelopment ? <UnderDevelopmentOverlay /> : renderTabContent()}
                </div>
            </div>
        </div>
    );
};
