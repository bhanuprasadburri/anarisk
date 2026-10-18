import React, { useEffect, useRef, useState } from 'react';
import { Bot, Info, Loader2, Send, Sparkles, FileText } from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/input';
import { ApiError } from '../services/apiClient';
import { assistantService } from '../services/assistantService';
import { useAuth } from '../hooks/useAuth';
import { cn } from '../lib/utils';
import { AssistantAskResponse } from '../types';

interface ChatEntry {
  id: string;
  question: string;
  response?: AssistantAskResponse;
  error?: string;
}

const EXAMPLES = [
  'Which of my entities currently have a critical risk score?',
  'Summarize the open cases and who they are assigned to.',
  'What evidence exists for domain lookalike attacks?',
];

export const AssistantPage: React.FC = () => {
  const { user } = useAuth();
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [status, setStatus] = useState<{ provider: string; configured: boolean; note: string; model?: string | null } | null>(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    assistantService
      .status()
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setStatusLoaded(true));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [entries, sending]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 2 || sending) return;
    const id = `${Date.now()}`;
    setEntries((prev) => [...prev, { id, question: q }]);
    setQuestion('');
    setSending(true);
    try {
      const response = await assistantService.ask(q);
      setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, response } : e)));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'The assistant is unreachable right now.';
      setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, error: msg } : e)));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-4xl flex-col">
      <PageHeader
        title="AI Assistant"
        description="Ask questions about your own records. Answers cite the record ids they came from — and say so when evidence is thin."
        actions={
          statusLoaded && status ? (
            <Badge tone={status.configured ? 'success' : 'warning'} dot>
              {status.configured ? `AI: ${status.provider}${status.model ? ` · ${status.model}` : ''}` : 'Retrieval mode (no AI provider)'}
            </Badge>
          ) : null
        }
      />

      {statusLoaded && status && !status.configured && (
        <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-warning-100 bg-warning-100/50 px-3.5 py-2.5">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning-600" />
          <p className="text-[12.5px] leading-snug text-ink-700">{status.note}</p>
        </div>
      )}

      <Card className="flex min-h-0 flex-1 flex-col">
        <CardContent className="flex min-h-0 flex-1 flex-col pt-5">
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto scrollbar-thin pr-1">
            {entries.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-gradient-soft text-brand-500">
                  <Sparkles className="h-6 w-6" />
                </span>
                <h3 className="mt-4 text-[15px] font-bold text-ink">Ask about your data</h3>
                <p className="mt-1 max-w-md text-[13px] text-muted">
                  The assistant only sees records you're authorized to view, and every claim links back to a cited
                  record. It never runs code or follows instructions embedded in your data.
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => ask(ex)}
                      className="rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink-700 transition-colors hover:border-brand-200 hover:bg-brand-50 hover:text-brand-700"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {entries.map((e) => (
              <div key={e.id} className="space-y-3">
                <div className="flex justify-end">
                  <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-gradient px-4 py-2.5 text-[13.5px] font-medium leading-relaxed text-white">
                    {e.question}
                  </p>
                </div>

                {e.error && (
                  <div className="flex gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-danger-100 text-danger">
                      <Bot className="h-4 w-4" />
                    </span>
                    <p className="rounded-2xl rounded-tl-md border border-danger-100 bg-danger-100/50 px-3.5 py-2.5 text-[13px] leading-relaxed text-danger-600">
                      {e.error}
                    </p>
                  </div>
                )}

                {e.response && (
                  <div className="flex gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                      <Bot className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="rounded-2xl rounded-tl-md border border-line bg-bg/70 px-4 py-3">
                        <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink-700">
                          {e.response.answer}
                        </p>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <Badge tone={e.response.used_ai ? 'violet' : 'default'}>
                          {e.response.used_ai ? `AI · ${e.response.provider}${e.response.model ? `/${e.response.model}` : ''}` : 'Deterministic retrieval'}
                        </Badge>
                        {e.response.cited.map((c) => (
                          <span
                            key={`${c.type}-${c.id}`}
                            title={c.title}
                            className="inline-flex max-w-[240px] items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] font-semibold text-ink-700"
                          >
                            <FileText className="h-3 w-3 shrink-0 text-brand-500" />
                            <span className="truncate">{c.title}</span>
                          </span>
                        ))}
                        {e.response.unsupported_citations.length > 0 && (
                          <span className="text-[11px] font-semibold text-warning-600">
                            {e.response.unsupported_citations.length} unsupported citation(s) dropped
                          </span>
                        )}
                      </div>
                      {e.response.limitation && (
                        <p className="mt-1.5 text-[11.5px] leading-snug text-warning-600">
                          <span className="font-semibold">Limitation:</span> {e.response.limitation}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {sending && (
              <div className="flex items-center gap-2.5 text-[13px] text-muted">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </span>
                Searching your records…
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
            className="mt-4 shrink-0 border-t border-line-soft pt-4"
          >
            <div className="flex items-end gap-2">
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    ask(question);
                  }
                }}
                rows={2}
                maxLength={2000}
                placeholder={`Ask ${user?.full_name?.split(' ')[0] || 'about'} your entities, cases and evidence… (Enter to send)`}
                className="min-h-[52px] resize-none"
              />
              <Button type="submit" size="lg" disabled={question.trim().length < 2 || sending} loading={sending}>
                <Send className="h-4 w-4" />
              </Button>
            </div>
            <p className={cn('mt-1.5 text-[11px] text-faint')}>
              Grounded in your records only. Model output is validated against retrieved ids — citations that don't
              match a real record are dropped, not shown.
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default AssistantPage;
