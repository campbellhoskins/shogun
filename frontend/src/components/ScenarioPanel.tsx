import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import type { Scenario, ScenarioLogLine, ScenarioUpdate } from '../types';
import '../styles/ScenarioPanel.css';

interface Props {
  scenarios: Scenario[];
  onScenarioActivate: (active: boolean) => void;
  onScenarioStep: (update: ScenarioUpdate) => void;
}

type Mode = 'scripted' | 'live';

export default function ScenarioPanel({ scenarios, onScenarioActivate, onScenarioStep }: Props) {
  const [mode, setMode] = useState<Mode>('scripted');

  // Shared step playback state
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);
  const [visibleLogLines, setVisibleLogLines] = useState<ScenarioLogLine[]>([]);
  const [showResults, setShowResults] = useState(false);

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
  const onScenarioActivateRef = useRef(onScenarioActivate);
  onScenarioActivateRef.current = onScenarioActivate;
  const onScenarioStepRef = useRef(onScenarioStep);
  onScenarioStepRef.current = onScenarioStep;

  const currentStep = activeScenario?.steps[currentStepIndex] || null;
  const totalSteps = activeScenario?.steps.length || 0;

  // Cleanup log timers
  const clearLogTimers = useCallback(() => {
    logTimersRef.current.forEach(clearTimeout);
    logTimersRef.current = [];
  }, []);

  // Compute cumulative revealed sets up to a given step index
  const computeRevealed = useCallback((scenario: Scenario, upToStep: number) => {
    const revealedNodes = new Set<string>();
    const revealedEdges = new Set<string>();
    for (let i = 0; i <= upToStep && i < scenario.steps.length; i++) {
      scenario.steps[i].highlight_nodes.forEach((n) => revealedNodes.add(n));
      scenario.steps[i].highlight_edges.forEach((e) => revealedEdges.add(e));
    }
    return { revealedNodes, revealedEdges };
  }, []);

  // Apply step: compute progressive reveal + stagger log lines
  const applyStep = useCallback((stepIndex: number) => {
    if (!activeScenario) return;
    const step = activeScenario.steps[stepIndex];
    if (!step) return;

    const { revealedNodes, revealedEdges } = computeRevealed(activeScenario, stepIndex);

    onScenarioStepRef.current({
      revealedNodeIds: revealedNodes,
      revealedEdgeKeys: revealedEdges,
      currentNodeIds: new Set(step.highlight_nodes),
      currentEdgeKeys: new Set(step.highlight_edges),
    });

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
  }, [activeScenario, computeRevealed, clearLogTimers]);

  // Step navigation
  const goStep = useCallback((index: number) => {
    if (index < 0 || index >= totalSteps) return;
    setShowResults(false);
    setCurrentStepIndex(index);
  }, [totalSteps]);

  // Go to results view
  const goToResults = useCallback(() => {
    setIsAutoPlaying(false);
    setShowResults(true);
  }, []);

  // Activate a scenario (from either mode)
  const activateScenario = useCallback((scenario: Scenario) => {
    clearLogTimers();
    setActiveScenario(scenario);
    setCurrentStepIndex(0);
    setIsAutoPlaying(false);
    setVisibleLogLines([]);
    setShowResults(false);
    onScenarioActivateRef.current(true);
  }, [clearLogTimers]);

  // Exit scenario — restore full graph
  const exitScenario = useCallback(() => {
    clearLogTimers();
    setActiveScenario(null);
    setCurrentStepIndex(0);
    setIsAutoPlaying(false);
    setVisibleLogLines([]);
    setShowResults(false);
    onScenarioActivateRef.current(false);
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
    setShowResults(false);
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
            setShowResults(true);
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
    if (activeScenario && currentStepIndex >= 0 && !showResults) {
      applyStep(currentStepIndex);
    }
  }, [currentStepIndex, activeScenario, applyStep, showResults]);

  // Auto-scroll log to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [visibleLogLines]);

  // Keyboard navigation (document-level)
  useEffect(() => {
    if (!activeScenario) return;

    const handler = (e: KeyboardEvent) => {
      // Don't interfere with input elements
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (showResults) return;
        setCurrentStepIndex((prev) => {
          if (prev >= totalSteps - 1) {
            setIsAutoPlaying(false);
            setShowResults(true);
            return prev;
          }
          setShowResults(false);
          return prev + 1;
        });
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (showResults) {
          setShowResults(false);
          return;
        }
        setCurrentStepIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === 'Escape') {
        e.preventDefault();
        exitScenario();
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [activeScenario, totalSteps, showResults, exitScenario]);

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
    setShowResults(false);
    setLivePrompt('');
    setLiveLoading(false);
    clearLogTimers();
    onScenarioActivateRef.current(false);
  }, [scenarios, clearLogTimers]);

  // Switch mode resets active scenario
  const handleModeSwitch = useCallback((newMode: Mode) => {
    if (newMode === mode) return;
    setMode(newMode);
    exitScenario();
  }, [mode, exitScenario]);

  // Compute results stats
  const resultsStats = activeScenario ? (() => {
    const { revealedNodes, revealedEdges } = computeRevealed(activeScenario, totalSteps - 1);
    const decisions = activeScenario.steps.reduce((count, step) =>
      count + step.log.filter((l) => l.type === 'decision').length, 0);
    return {
      nodes: revealedNodes.size,
      edges: revealedEdges.size,
      steps: totalSteps,
      decisions,
    };
  })() : null;

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

      {/* Results View */}
      {showResults && activeScenario && resultsStats && (
        <div className="scenario-results">
          <div className="scenario-results-badge">COMPLETE</div>
          <div className="scenario-results-name">{activeScenario.name}</div>

          <div className="scenario-results-grid">
            <div className="scenario-stat">
              <div className="scenario-stat-value">{resultsStats.nodes}</div>
              <div className="scenario-stat-label">Nodes Traversed</div>
            </div>
            <div className="scenario-stat">
              <div className="scenario-stat-value">{resultsStats.edges}</div>
              <div className="scenario-stat-label">Edges Followed</div>
            </div>
            <div className="scenario-stat">
              <div className="scenario-stat-value">{resultsStats.steps}</div>
              <div className="scenario-stat-label">Steps</div>
            </div>
            <div className="scenario-stat">
              <div className="scenario-stat-value">{resultsStats.decisions}</div>
              <div className="scenario-stat-label">Decisions</div>
            </div>
          </div>

          <div className="scenario-results-hint">
            The agent traversed the ontology graph using only structural relationships — no access to the raw document.
          </div>

          <div className="scenario-results-actions">
            <button className="scenario-btn-replay" onClick={() => { setShowResults(false); setCurrentStepIndex(0); }}>
              Replay
            </button>
            <button className="scenario-btn-exit" onClick={exitScenario}>
              Exit
            </button>
          </div>
        </div>
      )}

      {/* Step Content (shared between both modes) */}
      {currentStep && !showResults && (
        <>
          {/* Step progress dots */}
          <div className="scenario-step-dots">
            {activeScenario!.steps.map((_, i) => (
              <button
                key={i}
                className={`scenario-dot ${i < currentStepIndex ? 'completed' : i === currentStepIndex ? 'current' : ''}`}
                onClick={() => goStep(i)}
                title={`Step ${i + 1}`}
              />
            ))}
          </div>

          <div className="scenario-step-header">
            <div className="scenario-step-counter">
              Step {currentStepIndex + 1} / {totalSteps}
            </div>
            <div className="scenario-step-title">{currentStep.title}</div>
            <div className="scenario-step-description">{currentStep.description}</div>
          </div>

          {/* Manual Annotation */}
          {currentStep.annotation && (
            <div className="scenario-annotation">
              <div className="scenario-annotation-label">Manual Annotation</div>
              <div className="scenario-annotation-text">{currentStep.annotation}</div>
            </div>
          )}

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
              onClick={() => {
                if (currentStepIndex >= totalSteps - 1) {
                  goToResults();
                } else {
                  goStep(currentStepIndex + 1);
                }
              }}
            >
              {currentStepIndex >= totalSteps - 1 ? 'Results' : 'Next'}
            </button>
            <button
              className={`scenario-btn-auto ${isAutoPlaying ? 'playing' : ''}`}
              onClick={() => setIsAutoPlaying(!isAutoPlaying)}
            >
              {isAutoPlaying ? 'Pause' : 'Auto'}
            </button>
          </div>

          <div className="scenario-keyboard-hint">
            Use arrow keys to navigate, Esc to exit
          </div>
        </>
      )}
    </div>
  );
}
