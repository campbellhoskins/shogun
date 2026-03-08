import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import type { Scenario, ScenarioLogLine } from '../types';
import '../styles/ScenarioPanel.css';

interface Props {
  scenarios: Scenario[];
  onHighlight: (nodeIds: Set<string>, edgeKeys: Set<string>) => void;
  onClearHighlights: () => void;
  onFocusNode: (entityId: string) => void;
}

type Mode = 'scripted' | 'live';

export default function ScenarioPanel({ scenarios, onHighlight, onClearHighlights, onFocusNode }: Props) {
  const [mode, setMode] = useState<Mode>('scripted');

  // Shared step playback state
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);
  const [visibleLogLines, setVisibleLogLines] = useState<ScenarioLogLine[]>([]);

  // Scripted mode state
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Live mode state
  const [livePrompt, setLivePrompt] = useState('');
  const [liveLoading, setLiveLoading] = useState(false);

  const logTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const autoPlayRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Stable refs for callbacks to avoid render loops
  const onHighlightRef = useRef(onHighlight);
  onHighlightRef.current = onHighlight;
  const onFocusNodeRef = useRef(onFocusNode);
  onFocusNodeRef.current = onFocusNode;

  const currentStep = activeScenario?.steps[currentStepIndex] || null;
  const totalSteps = activeScenario?.steps.length || 0;

  // Cleanup log timers
  const clearLogTimers = useCallback(() => {
    logTimersRef.current.forEach(clearTimeout);
    logTimersRef.current = [];
  }, []);

  // Apply step: highlight + focus + stagger log lines
  const applyStep = useCallback((stepIndex: number) => {
    if (!activeScenario) return;
    const step = activeScenario.steps[stepIndex];
    if (!step) return;

    onHighlightRef.current(new Set(step.highlight_nodes), new Set(step.highlight_edges));
    if (step.focus_node) {
      onFocusNodeRef.current(step.focus_node);
    }

    clearLogTimers();

    const previousLines: ScenarioLogLine[] = [];
    for (let i = 0; i < stepIndex; i++) {
      previousLines.push(...activeScenario.steps[i].log);
    }
    setVisibleLogLines([...previousLines]);

    step.log.forEach((line, i) => {
      const timer = setTimeout(() => {
        setVisibleLogLines((prev) => [...prev, line]);
      }, (i + 1) * 120);
      logTimersRef.current.push(timer);
    });
  }, [activeScenario, clearLogTimers]);

  // Step navigation
  const goStep = useCallback((index: number) => {
    if (index < 0 || index >= totalSteps) return;
    setCurrentStepIndex(index);
  }, [totalSteps]);

  // Activate a scenario (from either mode)
  const activateScenario = useCallback((scenario: Scenario) => {
    clearLogTimers();
    setActiveScenario(scenario);
    setCurrentStepIndex(0);
    setIsAutoPlaying(false);
    setVisibleLogLines([]);
  }, [clearLogTimers]);

  // Select scripted scenario
  const handleSelectScenario = useCallback((scenarioId: string) => {
    setSelectedScenarioId(scenarioId);
    setDropdownOpen(false);
    const scenario = scenarios.find((s) => s.id === scenarioId);
    if (scenario) activateScenario(scenario);
  }, [scenarios, activateScenario]);

  // Run live walkthrough
  const handleRunWalkthrough = useCallback(async () => {
    const prompt = livePrompt.trim();
    if (!prompt || liveLoading) return;

    setLiveLoading(true);
    setActiveScenario(null);
    setVisibleLogLines([]);
    clearLogTimers();

    try {
      const scenario = await api.runWalkthrough(prompt);
      activateScenario(scenario);
    } catch (err) {
      console.error('Walkthrough failed:', err);
    } finally {
      setLiveLoading(false);
    }
  }, [livePrompt, liveLoading, clearLogTimers, activateScenario]);

  // Auto-play
  useEffect(() => {
    if (isAutoPlaying && activeScenario) {
      autoPlayRef.current = setInterval(() => {
        setCurrentStepIndex((prev) => {
          const next = prev + 1;
          if (next >= activeScenario.steps.length) {
            setIsAutoPlaying(false);
            return prev;
          }
          return next;
        });
      }, 4000);
    } else if (autoPlayRef.current) {
      clearInterval(autoPlayRef.current);
      autoPlayRef.current = null;
    }

    return () => {
      if (autoPlayRef.current) {
        clearInterval(autoPlayRef.current);
        autoPlayRef.current = null;
      }
    };
  }, [isAutoPlaying, activeScenario]);

  // Apply step when currentStepIndex changes
  useEffect(() => {
    if (activeScenario && currentStepIndex >= 0) {
      applyStep(currentStepIndex);
    }
  }, [currentStepIndex, activeScenario, applyStep]);

  // Auto-scroll log to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [visibleLogLines]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearLogTimers();
      if (autoPlayRef.current) clearInterval(autoPlayRef.current);
    };
  }, [clearLogTimers]);

  // Reset when scenarios change (graph switch)
  useEffect(() => {
    setSelectedScenarioId(null);
    setActiveScenario(null);
    setCurrentStepIndex(0);
    setIsAutoPlaying(false);
    setVisibleLogLines([]);
    setLivePrompt('');
    setLiveLoading(false);
    clearLogTimers();
    onClearHighlights();
  }, [scenarios, clearLogTimers, onClearHighlights]);

  // Switch mode resets active scenario
  const handleModeSwitch = useCallback((newMode: Mode) => {
    if (newMode === mode) return;
    setMode(newMode);
    setActiveScenario(null);
    setCurrentStepIndex(0);
    setIsAutoPlaying(false);
    setVisibleLogLines([]);
    clearLogTimers();
    onClearHighlights();
  }, [mode, clearLogTimers, onClearHighlights]);

  return (
    <div className="scenario-panel">
      {/* Mode Toggle */}
      <div className="scenario-mode-toggle">
        <button
          className={`scenario-mode-btn ${mode === 'scripted' ? 'active' : ''}`}
          onClick={() => handleModeSwitch('scripted')}
        >
          Scripted
        </button>
        <button
          className={`scenario-mode-btn ${mode === 'live' ? 'active' : ''}`}
          onClick={() => handleModeSwitch('live')}
        >
          Live
        </button>
      </div>

      {/* Scripted Mode */}
      {mode === 'scripted' && (
        <>
          {scenarios.length === 0 ? (
            <div className="scenario-empty">
              <div className="scenario-empty-icon">{'\uD83C\uDFAF'}</div>
              <div className="scenario-empty-title">No scenarios available</div>
              <div className="scenario-empty-hint">
                Scenarios are tied to specific graphs. Switch to a graph that has scenario data to see operational walkthroughs.
              </div>
            </div>
          ) : (
            <div className="scenario-selector">
              <button
                className="scenario-selector-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
              >
                <span>{activeScenario && selectedScenarioId ? activeScenario.name : 'Select a scenario...'}</span>
                <span className={`chevron ${dropdownOpen ? 'open' : ''}`}>{'\u25BC'}</span>
              </button>
              {dropdownOpen && (
                <div className="scenario-dropdown">
                  {scenarios.map((s) => (
                    <button
                      key={s.id}
                      className={`scenario-option ${s.id === selectedScenarioId ? 'active' : ''}`}
                      onClick={() => handleSelectScenario(s.id)}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Live Mode */}
      {mode === 'live' && (
        <div className="live-walkthrough-input">
          <div className="live-prompt-label">Describe a scenario for the agent to analyze:</div>
          <input
            className="live-prompt-input"
            placeholder="e.g. A Level 3 earthquake hits — trace the full response chain"
            value={livePrompt}
            onChange={(e) => setLivePrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleRunWalkthrough();
              }
            }}
            disabled={liveLoading}
          />
          <button
            className="live-run-btn"
            onClick={handleRunWalkthrough}
            disabled={!livePrompt.trim() || liveLoading}
          >
            {liveLoading ? 'Running...' : 'Run'}
          </button>
          {liveLoading && (
            <div className="live-loading">
              <div className="live-loading-dots">
                <span className="live-loading-dot" />
                <span className="live-loading-dot" />
                <span className="live-loading-dot" />
              </div>
              <span className="live-loading-text">Agent traversing graph...</span>
            </div>
          )}
        </div>
      )}

      {/* Step Content (shared between both modes) */}
      {currentStep && (
        <>
          <div className="scenario-step-header">
            <div className="scenario-step-counter">
              Step {currentStepIndex + 1} / {totalSteps}
            </div>
            <div className="scenario-step-title">{currentStep.title}</div>
            <div className="scenario-step-description">{currentStep.description}</div>
          </div>

          <div className="scenario-log">
            {visibleLogLines.map((line, i) => (
              <div key={i} className={`scenario-log-line log-${line.type}`}>
                {line.text}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>

          <div className="scenario-controls">
            <button
              className="scenario-btn-prev"
              onClick={() => goStep(currentStepIndex - 1)}
              disabled={currentStepIndex === 0}
            >
              Prev
            </button>
            <button
              className="scenario-btn-next"
              onClick={() => goStep(currentStepIndex + 1)}
              disabled={currentStepIndex >= totalSteps - 1}
            >
              Next
            </button>
            <button
              className={`scenario-btn-auto ${isAutoPlaying ? 'playing' : ''}`}
              onClick={() => setIsAutoPlaying(!isAutoPlaying)}
            >
              {isAutoPlaying ? 'Pause' : 'Auto'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
