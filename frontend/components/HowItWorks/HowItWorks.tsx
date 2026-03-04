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

export const HowItWorks: React.FC = () => {
    const [activeTab, setActiveTab] = useState<TabId>('overview');

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
                            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Tab Content */}
            <div className="how-it-works-content">
                <div className="content-wrapper">
                    {renderTabContent()}
                </div>
            </div>
        </div>
    );
};
