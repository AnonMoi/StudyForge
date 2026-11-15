import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Note, ReviewCard, ReviewErrorAnalysis, ReviewHistory, ReviewStats } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };
type CardType = "qa" | "code" | "explain" | "transfer";
type GenerationPreview = { cards: { front: string; back: string; hint: string; source_note_id: number }[]; sourceNoteId: number };

const cardTypeLabels: Record<string, string> = {
  qa: "问答",
  code: "代码",
  explain: "用自己的话解释",
  transfer: "换个场景应用",
};

const errorTypeLabels: Record<string, string> = {
  "回忆不足": "没能完整想起来",
  forgotten: "没想起来",
  difficult: "想起来很吃力",
  incomplete: "只想起了一部分",
};

const qualityChoices = [
  { value: 0, label: "没想起来" },
  { value: 2, label: "想得很吃力" },
  { value: 3, label: "大致想起来" },
  { value: 4, label: "比较顺" },
  { value: 5, label: "已经很熟" },
];

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function readableDate(value: string) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(new Date(year, month - 1, day));
}

function qualityLabel(value: number) {
  return qualityChoices.find(item => item.value === value)?.label ?? "完成了一次复习";
}

function errorTypeLabel(value: string) {
  return errorTypeLabels[value] ?? value;
}

export function ReviewCardsWorkspace({ onNotice, onError }: Props) {
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [history, setHistory] = useState<Record<number, ReviewHistory[]>>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});
  const [editing, setEditing] = useState<number | null>(null);
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const [hint, setHint] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [generationNote, setGenerationNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [errorAnalysis, setErrorAnalysis] = useState<ReviewErrorAnalysis | null>(null);
  const [cardType, setCardType] = useState<CardType>("qa");
  const [generationPreview, setGenerationPreview] = useState<GenerationPreview | null>(null);
  const [pendingBulk, setPendingBulk] = useState<"archive" | "delete" | null>(null);
  const [pendingArchive, setPendingArchive] = useState<number | null>(null);

  async function load() {
    try {
      const [cardData, noteData, statData, analysisData] = await Promise.all([
        api.reviewCards(),
        api.notes(),
        api.reviewCardStats(),
        api.reviewErrorAnalysis(),
      ]);
      setCards(cardData);
      setNotes(noteData);
      setStats(statData);
      setErrorAnalysis(analysisData);
    } catch (error) {
      onError(error instanceof Error ? error.message : "复习卡片没有加载成功，请稍后再试。");
    } finally {
      setInitialLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  const today = localDateKey();
  const dueCards = useMemo(() => cards.filter(card => card.status === "active" && card.due_date <= today), [cards, today]);
  const laterCards = useMemo(() => cards.filter(card => card.status === "active" && card.due_date > today), [cards, today]);
  const archivedCards = useMemo(() => cards.filter(card => card.status === "archived"), [cards]);

  function toggleSelected(id: number) {
    setSelected(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id]);
    setPendingBulk(null);
  }

  async function createCard() {
    if (!front.trim()) return;
    setLoading(true);
    try {
      const payload = {
        front: front.trim(),
        back: back.trim(),
        hint: hint.trim(),
        card_type: cardType,
        source_note_id: sourceNote ? Number(sourceNote) : null,
      };
      if (editing !== null) {
        await api.updateReviewCard(editing, payload);
        onNotice("这张卡片已经改好了。");
      } else {
        await api.createReviewCard(payload);
        onNotice("新卡片已经放进今天的复习里。");
      }
      cancelEdit();
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : "卡片没有保存成功，请再试一次。");
    } finally {
      setLoading(false);
    }
  }

  function startEdit(card: ReviewCard) {
    setEditing(card.id);
    setFront(card.front);
    setBack(card.back);
    setHint(card.hint);
    setCardType((card.card_type as CardType) || "qa");
    setSourceNote(card.source_note_id ? String(card.source_note_id) : "");
  }

  function cancelEdit() {
    setEditing(null);
    setFront("");
    setBack("");
    setHint("");
    setCardType("qa");
    setSourceNote("");
  }

  async function generateFromNote() {
    if (!generationNote) return;
    setLoading(true);
    try {
      const noteId = Number(generationNote);
      const result = await api.generateReviewCards(noteId, false);
      if (result.reused) {
        setGenerationPreview(null);
        await load();
        onNotice("这篇笔记已经整理过，原来的卡片还在卡片盒里。");
        return;
      }
      setGenerationPreview({ cards: result.preview, sourceNoteId: noteId });
    } catch (error) {
      onError(error instanceof Error ? error.message : "暂时没能从这篇笔记整理卡片，请再试一次。");
    } finally {
      setLoading(false);
    }
  }

  async function confirmGeneration() {
    if (!generationPreview) return;
    setLoading(true);
    try {
      const result = await api.generateReviewCards(generationPreview.sourceNoteId, true);
      setGenerationPreview(null);
      await load();
      onNotice(`已经从笔记中整理出 ${result.cards.length} 张卡片。`);
    } catch (error) {
      onError(error instanceof Error ? error.message : "这些卡片没有保存成功，请再试一次。");
    } finally {
      setLoading(false);
    }
  }

  async function answer(card: ReviewCard, quality: number) {
    try {
      await api.answerReviewCard(card.id, quality, quality < 3 ? "回忆不足" : undefined, quality < 3 ? "这次还没能完整想起来" : undefined);
      setRevealed(current => ({ ...current, [card.id]: false }));
      setSelected(current => current.filter(id => id !== card.id));
      await load();
      onNotice(quality < 3 ? "记下了，下次会早点再看到这张卡片。" : "这次复习已经记下来了。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这次复习没有记下来，请再试一次。");
    }
  }

  async function bulk(action: "archive" | "delete") {
    if (!selected.length) return;
    const count = selected.length;
    try {
      await api.bulkReviewCards(selected, action);
      setSelected([]);
      setPendingBulk(null);
      await load();
      onNotice(action === "archive" ? `已经收起 ${count} 张卡片。` : `已经删除 ${count} 张卡片。`);
    } catch (error) {
      onError(error instanceof Error ? error.message : "这些卡片暂时没有处理成功，请再试一次。");
    }
  }

  async function archiveCard(cardId: number) {
    try {
      await api.archiveReviewCard(cardId);
      setPendingArchive(null);
      await load();
      onNotice("这张卡片已经收进卡片盒。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这张卡片暂时没有收起来，请再试一次。");
    }
  }

  async function restoreCard(cardId: number) {
    try {
      await api.bulkReviewCards([cardId], "restore");
      await load();
      onNotice("这张卡片已经放回复习安排。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这张卡片暂时没有恢复，请再试一次。");
    }
  }

  async function showHistory(cardId: number) {
    if (history[cardId]) return;
    try {
      const records = await api.reviewCardHistory(cardId);
      setHistory(current => ({ ...current, [cardId]: records }));
    } catch (error) {
      onError(error instanceof Error ? error.message : "以前的复习记录没有加载成功。");
    }
  }

  function libraryRow(card: ReviewCard, archived = false) {
    return <div className="review-library-row" key={card.id}>
      <div><strong>{card.front}</strong><span>{cardTypeLabels[card.card_type] ?? "复习卡片"} · {archived ? "已经收起" : `${readableDate(card.due_date)}再看`}</span></div>
      <div className="button-row">
        {!archived && <button type="button" className="text-button" onClick={() => startEdit(card)}>修改</button>}
        {archived ? <button type="button" className="text-button" onClick={() => void restoreCard(card.id)}>放回复习</button> : <button type="button" className="text-button" onClick={() => setPendingArchive(card.id)}>收起</button>}
      </div>
      {pendingArchive === card.id && !archived && <div className="review-inline-confirm"><span>收起后可以从卡片盒里恢复。</span><button type="button" className="ghost-button" onClick={() => void archiveCard(card.id)}>确认收起</button><button type="button" className="text-button" onClick={() => setPendingArchive(null)}>取消</button></div>}
    </div>;
  }

  if (initialLoading) {
    return <div className="review-cards-workspace"><section className="review-loading sf-open-section" aria-live="polite"><strong>正在打开今天的复习卡片…</strong><span>卡片和以前的复习记录会保留在本机。</span></section></div>;
  }

  return <div className="review-cards-workspace">
    <header className="review-page-heading">
      <div><h2>今天复习什么</h2><p>{dueCards.length ? `先完成眼前这 ${dueCards.length} 张，再去做新的内容。` : "今天没有到期卡片，可以整理一张以后要回看的内容。"}</p></div>
      <div className="review-overview" aria-label="复习卡片概况"><strong>{dueCards.length} 张今天要看</strong><span>卡片盒共 {stats?.total_cards ?? cards.length} 张</span>{stats && <span>其中 {stats.mastered_cards} 张已经比较熟</span>}</div>
    </header>

    <div className="review-desk">
      <section className="review-session" aria-labelledby="review-session-title">
        <div className="review-section-heading"><div><h3 id="review-session-title">今天的复习顺序</h3><p>先自己想，再打开答案；最后只要说这次想起来多少。</p></div>{dueCards.length > 0 && <span>{dueCards.length} 张</span>}</div>

        {selected.length > 0 && <div className="review-selection-bar"><span>选中了 {selected.length} 张</span><div className="button-row"><button type="button" className="ghost-button" onClick={() => setPendingBulk("archive")}>收进卡片盒</button><button type="button" className="text-button review-delete-button" onClick={() => setPendingBulk("delete")}>删除</button></div>{pendingBulk && <div className="review-inline-confirm"><span>{pendingBulk === "archive" ? "这些卡片以后还能从卡片盒恢复。" : "删除后不能恢复，确定要继续吗？"}</span><button type="button" className={pendingBulk === "delete" ? "danger-button" : "ghost-button"} onClick={() => void bulk(pendingBulk)}>{pendingBulk === "archive" ? "确认收起" : "确认删除"}</button><button type="button" className="text-button" onClick={() => setPendingBulk(null)}>取消</button></div>}</div>}

        {dueCards.length ? <ol className="review-queue">
          {dueCards.map((card, index) => <li key={card.id}><article className="review-card">
            <div className="review-card-meta"><label><input aria-label={`选择复习卡片：${card.front}`} type="checkbox" checked={selected.includes(card.id)} onChange={() => toggleSelected(card.id)} /><span>第 {index + 1} 张</span></label><span>{cardTypeLabels[card.card_type] ?? "复习卡片"} · {card.due_date < today ? `${readableDate(card.due_date)}原本要看` : "今天要看"}</span></div>
            <h3>{card.front}</h3>
            {revealed[card.id] ? <><div className="review-card-answer"><strong>我原来写的答案</strong><p>{card.back || "这张卡片还没有答案，可以先用自己的话补上一段。"}</p>{card.hint && <small>给自己的提示：{card.hint}</small>}</div><fieldset className="review-recall-choice"><legend>刚才想起来多少？</legend><div className="review-quality-options">{qualityChoices.map(choice => <button type="button" className="ghost-button" key={choice.value} aria-label={`${card.front}：${choice.label}`} onClick={() => void answer(card, choice.value)}>{choice.label}</button>)}</div></fieldset></> : <button type="button" className="primary-button review-reveal-button" onClick={() => setRevealed(current => ({ ...current, [card.id]: true }))}>想好后看答案</button>}
            <div className="review-card-tools"><button type="button" className="text-button" onClick={() => startEdit(card)}>修改这张卡</button><details className="review-history" onToggle={event => { if (event.currentTarget.open) void showHistory(card.id); }}><summary>以前怎么复习的</summary><div className="review-history-list">{history[card.id] ? history[card.id].length ? history[card.id].map(item => <div className="review-history-row" key={item.id}><span>{readableDate(item.reviewed_at.slice(0, 10))}</span><strong>{qualityLabel(item.quality)}</strong><small>复习后隔 {item.interval_after} 天再看</small></div>) : <span>这张卡片还没有以前的复习记录。</span> : <span>正在读取…</span>}</div></details><button type="button" className="text-button" onClick={() => setPendingArchive(card.id)}>暂时收起</button></div>
            {pendingArchive === card.id && <div className="review-inline-confirm"><span>收起后可以从卡片盒里恢复。</span><button type="button" className="ghost-button" onClick={() => void archiveCard(card.id)}>确认收起</button><button type="button" className="text-button" onClick={() => setPendingArchive(null)}>取消</button></div>}
          </article></li>)}
        </ol> : <div className="review-empty"><strong>今天的复习已经清空了</strong><p>如果刚学到一个容易忘的概念，可以在右边给以后留一张卡片。</p></div>}

        {(laterCards.length > 0 || archivedCards.length > 0) && <div className="review-library">{laterCards.length > 0 && <details><summary>之后再复习的卡片 <span>{laterCards.length} 张</span></summary><div>{laterCards.map(card => libraryRow(card))}</div></details>}{archivedCards.length > 0 && <details><summary>已经收起的卡片 <span>{archivedCards.length} 张</span></summary><div>{archivedCards.map(card => libraryRow(card, true))}</div></details>}</div>}
      </section>

      <aside className="review-card-editor" aria-labelledby="review-editor-title">
        <div className="review-section-heading"><div><h3 id="review-editor-title">整理复习卡片</h3><p>问题越具体，下次越容易知道自己是不是真的会了。</p></div></div>
        <details className="review-from-note"><summary>从一篇笔记里整理</summary><div className="stack-form"><label>选择笔记<select aria-label="选择要整理的笔记" value={generationNote} onChange={event => { setGenerationNote(event.target.value); setGenerationPreview(null); }}><option value="">先选一篇笔记</option>{notes.map(note => <option value={note.id} key={note.id}>{note.title}</option>)}</select></label><button type="button" className="ghost-button" disabled={!generationNote || loading} onClick={() => void generateFromNote()}>{loading ? "正在整理…" : "先看看会整理成什么"}</button><small>只有确认以后，卡片才会保存。</small></div></details>
        {generationPreview && <div className="review-generation-preview"><strong>准备留下 {generationPreview.cards.length} 张卡片</strong><div>{generationPreview.cards.map((item, index) => <article key={`${item.source_note_id}-${index}`}><strong>{item.front}</strong><p>{item.back.slice(0, 180)}</p></article>)}</div><div className="button-row"><button type="button" className="primary-button" onClick={() => void confirmGeneration()} disabled={loading}>{loading ? "正在保存…" : "把这些卡片留下"}</button><button type="button" className="ghost-button" onClick={() => setGenerationPreview(null)}>返回修改</button></div></div>}
        <form className="review-manual-form" onSubmit={event => { event.preventDefault(); void createCard(); }}>
          <div className="review-manual-heading"><strong>{editing === null ? "自己写一张" : "修改这张卡片"}</strong>{editing !== null && <button type="button" className="text-button" onClick={cancelEdit}>取消修改</button>}</div>
          <label>这是什么类型<select aria-label="卡片类型" value={cardType} onChange={event => setCardType(event.target.value as CardType)}><option value="qa">直接问答</option><option value="code">写出代码</option><option value="explain">用自己的话解释</option><option value="transfer">换个场景应用</option></select></label>
          <label>下次要问自己什么<input aria-label="卡片问题" value={front} onChange={event => setFront(event.target.value)} placeholder="例如：窗口函数和 GROUP BY 有什么不同？" /></label>
          <label>我希望自己想起什么<textarea aria-label="卡片答案" rows={5} value={back} onChange={event => setBack(event.target.value)} placeholder="用自己的话写答案，也可以暂时留空" /></label>
          <label>想不起来时给什么提示<input aria-label="卡片提示" value={hint} onChange={event => setHint(event.target.value)} placeholder="可选，留一个关键词就够了" /></label>
          <label>这张卡来自哪里<select aria-label="卡片来源笔记" value={sourceNote} onChange={event => setSourceNote(event.target.value)}><option value="">没有关联笔记</option>{notes.map(note => <option value={note.id} key={note.id}>{note.title}</option>)}</select></label>
          <div className="review-form-footer"><span>{editing === null ? "新卡片会从今天开始复习。" : "以前的复习记录会继续保留。"}</span><button type="submit" className="primary-button" disabled={!front.trim() || loading}>{loading ? "正在保存…" : editing === null ? "留下这张卡片" : "保存修改"}</button></div>
        </form>
      </aside>
    </div>

    {errorAnalysis && errorAnalysis.total_errors > 0 && <details className="review-patterns"><summary><span><strong>最近哪些内容容易忘</strong><small>只在需要时展开，不影响今天的复习。</small></span><b>近 {errorAnalysis.days} 天 · {errorAnalysis.total_errors} 次没想牢</b></summary><div className="review-patterns-body"><section><h3>容易卡住的情况</h3>{Object.entries(errorAnalysis.by_error_type).length ? Object.entries(errorAnalysis.by_error_type).map(([name, count]) => <p key={name}><span>{errorTypeLabel(name)}</span><strong>{count} 次</strong></p>) : <p>暂时没有重复出现的情况。</p>}</section><section><h3>需要多看几次的主题</h3>{Object.entries(errorAnalysis.by_topic).length ? Object.entries(errorAnalysis.by_topic).map(([name, count]) => <p key={name}><span>{name}</span><strong>{count} 次</strong></p>) : <p>暂时还看不出集中在哪个主题。</p>}</section>{errorAnalysis.recommendations.length > 0 && <section className="review-next-practice"><h3>下次可以怎么练</h3>{errorAnalysis.recommendations.map(item => <p key={item.error_type}><strong>{errorTypeLabel(item.error_type)}</strong><span>{item.action}</span></p>)}</section>}</div></details>}
  </div>;
}
