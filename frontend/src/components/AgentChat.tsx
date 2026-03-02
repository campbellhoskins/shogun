import { useState, useRef, useCallback, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import type { ChatMessage } from '../types';
import EntityChip from './EntityChip';
import '../styles/AgentChat.css';

interface Props {
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  typeColors: Record<string, string>;
  onEntitySelect: (entityId: string) => void;
}

export default function AgentChat({ messages, onMessagesChange, typeColors, onEntitySelect }: Props) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || loading) return;

    setInput('');

    const userMsg: ChatMessage = {
      role: 'user',
      content: question,
      timestamp: Date.now(),
    };

    const newMessages = [...messages, userMsg];
    onMessagesChange(newMessages);
    setLoading(true);

    try {
      const response = await api.askAgent(question);
      const agentMsg: ChatMessage = {
        role: 'agent',
        content: response.answer,
        referenced_entities: response.referenced_entities,
        timestamp: Date.now(),
      };
      onMessagesChange([...newMessages, agentMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        role: 'agent',
        content: 'Sorry, an error occurred while processing your question. Please try again.',
        timestamp: Date.now(),
      };
      onMessagesChange([...newMessages, errorMsg]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [input, loading, messages, onMessagesChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="agent-chat">
      <div className="agent-chat-messages">
        {messages.length === 0 && !loading && (
          <div className="agent-chat-empty">
            <div className="agent-chat-empty-title">Policy Intelligence Agent</div>
            <div className="agent-chat-empty-hint">
              Ask questions about the ontology graph. The agent explores the graph
              using tools — it has no access to the raw document.
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`chat-message chat-message-${msg.role}`}>
            <div className="chat-message-content">
              {msg.role === 'agent' ? (
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
            {msg.referenced_entities && msg.referenced_entities.length > 0 && (
              <div className="chat-message-refs">
                <span className="chat-message-refs-label">Referenced entities:</span>
                {msg.referenced_entities.map((ent) => (
                  <EntityChip
                    key={ent.id}
                    name={ent.name}
                    type={ent.type}
                    color={typeColors[ent.type]}
                    onClick={() => onEntitySelect(ent.id)}
                  />
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="chat-thinking">
            <div className="chat-thinking-dots">
              <span className="chat-thinking-dot" />
              <span className="chat-thinking-dot" />
              <span className="chat-thinking-dot" />
            </div>
            <span className="chat-thinking-text">Querying graph...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="agent-chat-input-area">
        <div className="agent-chat-input-wrap">
          <input
            ref={inputRef}
            className="agent-chat-input"
            placeholder="Ask about the policy..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            className="agent-chat-send"
            onClick={handleSend}
            disabled={!input.trim() || loading}
          >
            {'\u2191'}
          </button>
        </div>
      </div>
    </div>
  );
}
