import { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type {
  CapabilityAssessment,
  CapabilityEvidenceResponse,
  CapabilityProfile,
  PlanProposal,
} from "./types";

type Props = {
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

function stageLabel(level: number) {
  if (level < 1.5) return "刚开始接触";
  if (level < 3.5) return "正在打基础";
  if (level < 5.5) return "能够独立运用";
  if (level < 7) return "已经比较熟练";
  return "已经很扎实";
}

function evidenceReadiness(confidence: number, count: number) {
  if (!count) return "暂时没有足够的学习记录";
  if (confidence < 0.45) return "还需要更多练习记录";
  if (confidence < 0.8) return "已经有一些依据";
  return "学习依据比较充分";
}

function sourceLabel(source: unknown) {
  const labels: Record<string, string> = {
    task: "完成的任务",
    daily_log: "学习记录",
    project_milestone: "项目成果",
    topic: "知识主题",
    teaching_attempt: "讲解练习",
    practice_attempt: "练习作答",
    code_run: "代码练习",
  };
  return labels[String(source)] ?? "学习记录";
}

export default function CapabilitiesWorkspace({ onNotice, onError }: Props) {
  const [profiles, setProfiles] = useState<CapabilityProfile[]>([]);
  const [history, setHistory] = useState<Record<number, CapabilityAssessment[]>>({});
  const [evidence, setEvidence] = useState<Record<number, CapabilityEvidenceResponse>>({});
  const [proposals, setProposals] = useState<Record<number, PlanProposal>>({});
  const [loading, setLoading] = useState(true);
  const [assessing, setAssessing] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setProfiles((await api.capabilities()).profiles);
    } catch (error) {
      onError(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function assess() {
    setAssessing(true);
    try {
      await api.assessCapabilities();
      setProfiles((await api.capabilities()).profiles);
      setHistory({});
      setEvidence({});
      setProposals({});
      onNotice("已经根据最近的学习记录更新了能力回看。");
    } catch (error) {
      onError(getApiErrorMessage(error));
    } finally {
      setAssessing(false);
    }
  }

  async function showHistory(id: number) {
    try {
      const data = await api.capabilityHistory(id);
      setHistory(current => ({ ...current, [id]: data }));
    } catch (error) {
      onError(getApiErrorMessage(error));
    }
  }

  async function showEvidence(id: number) {
    try {
      const data = await api.capabilityEvidence(id);
      setEvidence(current => ({ ...current, [id]: data }));
    } catch (error) {
      onError(getApiErrorMessage(error));
    }
  }

  async function propose(profile: CapabilityProfile) {
    try {
      const proposal = await api.proposeCapabilityPlan(profile.id);
      setProposals(current => ({ ...current, [profile.id]: proposal }));
    } catch (error) {
      onError(getApiErrorMessage(error));
    }
  }

  async function execute(profileId: number, proposal: PlanProposal) {
    try {
      const result = await api.executePlanProposal(proposal.proposal_id, true);
      setProposals(current => ({ ...current, [profileId]: result }));
      await load();
      onNotice(result.executed ? "相关练习已经重新安排到学习计划。" : "这次没有调整学习计划。");
    } catch (error) {
      onError(getApiErrorMessage(error));
    }
  }

  return (
    <section className="capability-workspace sf-open-section">
      <div className="capability-page-heading sf-surface-header">
        <div>
          <h2 className="sf-section-title">我目前会什么</h2>
          <p className="sf-surface-description">只参考已经保存的任务、练习、项目和学习记录，不把一次结果当成定论。</p>
        </div>
        <button className="primary-button" onClick={() => void assess()} disabled={assessing}>
          {assessing ? "正在整理…" : "根据最近记录更新"}
        </button>
      </div>

      {loading && <div className="empty"><p>正在整理最近的学习记录…</p></div>}

      {!loading && !profiles.length && (
        <div className="empty capability-empty">
          <strong>还没有形成能力回看</strong>
          <p>先完成一些任务、练习或学习记录，再根据最近记录更新。</p>
          <button type="button" className="secondary-button" onClick={() => void assess()} disabled={assessing}>
            现在整理一次
          </button>
        </div>
      )}

      {!loading && (
        <div className="capability-grid">
          {profiles.map(profile => {
            const proposal = proposals[profile.id];
            const linked = evidence[profile.id];
            const changes = history[profile.id]?.filter(item => item.previous_level !== item.new_level);
            const otherEvidenceCount = profile.evidence.length;

            return (
              <article className="capability-card" key={profile.id}>
                <div className="capability-card-header">
                  <div><strong>{profile.name}</strong></div>
                  <div className="capability-stage">
                    <span>目前</span>
                    <strong>{stageLabel(profile.level)}</strong>
                  </div>
                </div>

                <div
                  className="capability-meter"
                  role="progressbar"
                  aria-label={`${profile.name}学习积累`}
                  aria-valuemin={0}
                  aria-valuemax={8}
                  aria-valuenow={profile.level}
                >
                  <span style={{ width: `${Math.min(100, profile.level / 8 * 100)}%` }} />
                </div>

                <div className="capability-meta">
                  <span>{profile.evidence_count ? `参考了 ${profile.evidence_count} 条学习记录` : evidenceReadiness(profile.confidence, 0)}</span>
                  {profile.evidence_count > 0 && <span>{evidenceReadiness(profile.confidence, profile.evidence_count)}</span>}
                </div>
                {profile.last_assessed_at && (
                  <small className="capability-updated-at">最近更新：{new Date(profile.last_assessed_at).toLocaleString()}</small>
                )}

                <div className="button-row capability-actions">
                  <button type="button" className="ghost-button" onClick={() => void showHistory(profile.id)}>看看变化</button>
                  <button type="button" className="ghost-button" onClick={() => void showEvidence(profile.id)}>查看练习和错题</button>
                  <button type="button" className="ghost-button" onClick={() => void propose(profile)}>安排巩固练习</button>
                </div>

                {linked && (
                  <div className="capability-evidence-panel">
                    <div className="capability-section-heading">
                      <strong>相关练习和错题</strong>
                      <span>这些记录参与了当前判断</span>
                    </div>
                    <div className="capability-evidence-stats">
                      <span>{linked.practice.exercise_count} 道练习</span>
                      <span>{linked.practice.attempt_count} 次作答</span>
                      <span>{linked.practice.pass_rate === null ? "还没有通过记录" : `通过率 ${Math.round(linked.practice.pass_rate * 100)}%`}</span>
                      <span>{linked.review.card_count} 张错题卡</span>
                      <span>{linked.review.error_event_count} 次需要回看</span>
                    </div>
                    {linked.practice.exercises.map(exercise => (
                      <div className="capability-evidence-row" key={`exercise-${exercise.id}`}>
                        <span>{exercise.title}</span>
                        <small>
                          {exercise.attempts.length
                            ? `${exercise.attempts.filter(attempt => attempt.passed).length} 次通过 · ${exercise.attempts.filter(attempt => !attempt.passed).length} 次还需练习`
                            : "还没有作答"}
                        </small>
                      </div>
                    ))}
                    {linked.review.cards.map(card => (
                      <div className="capability-evidence-row" key={`review-${card.id}`}>
                        <span>{card.front}</span>
                        <small>{card.error_events.length ? `回看了 ${card.error_events.length} 次` : `${card.error_type ?? "需要回看"} · ${card.error_count} 次`}</small>
                      </div>
                    ))}
                    {!linked.practice.exercises.length && !linked.review.cards.length && <small>目前还没有直接相关的练习或错题。</small>}
                  </div>
                )}

                {changes && (
                  <div className="capability-history-panel">
                    <div className="capability-section-heading">
                      <strong>这项能力的变化</strong>
                      <span>按学习记录更新时间排列</span>
                    </div>
                    {changes.length ? changes.slice(0, 8).map(item => (
                      <div className="capability-history-row" key={item.id}>
                        <span>{new Date(item.created_at).toLocaleDateString()}</span>
                        <strong>{stageLabel(item.previous_level)} → {stageLabel(item.new_level)}</strong>
                        <small>参考 {item.evidence_count} 条记录</small>
                      </div>
                    )) : <small>目前还没有明显的阶段变化。</small>}
                  </div>
                )}

                {proposal && (
                  <div className="capability-plan-preview">
                    <div className="capability-section-heading">
                      <strong>可以怎样巩固</strong>
                      <span>{proposal.changes.length ? `涉及 ${proposal.changes.length} 项已有任务` : "暂时不用调整"}</span>
                    </div>
                    {proposal.changes.length ? proposal.changes.slice(0, 5).map((change, index) => {
                      const after = change.after as Record<string, unknown> | undefined;
                      return <p key={index}>相关任务 {index + 1}{after?.due_date ? ` · 安排到 ${String(after.due_date)}` : " · 保持原来的时间"}</p>;
                    }) : <p>现有计划里没有需要重新安排的相关任务，可以先继续积累练习记录。</p>}
                    {proposal.requires_confirmation && proposal.changes.length > 0 && (
                      <button type="button" className="primary-button" onClick={() => void execute(profile.id, proposal)}>
                        把这些练习重新排好
                      </button>
                    )}
                    {proposal.executed && <small>已经更新到学习计划，可以去计划页查看。</small>}
                  </div>
                )}

                <details className="capability-other-evidence">
                  <summary>{otherEvidenceCount ? `其它参考记录 · ${otherEvidenceCount}` : "暂无其它参考记录"}</summary>
                  <div className="evidence-list">
                    {otherEvidenceCount ? profile.evidence.map((item, index) => (
                      <div className="evidence-row" key={`${profile.id}-${index}`}>
                        <strong>{sourceLabel(item.source_type)}</strong>
                        <span>参与了这次能力回看</span>
                      </div>
                    )) : <p>完成更多学习内容后，相关记录会出现在这里。</p>}
                  </div>
                </details>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
