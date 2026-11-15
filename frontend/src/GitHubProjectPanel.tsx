import { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { GitHubAnalysisResponse, GitHubCommit, GitHubLinkPreview, GitHubRepository, GitHubSyncPreview } from "./types";

type Props = { projectId: number; onNotice: (message: string) => void; onError: (message: string) => void };

type SyncResult = GitHubSyncPreview & { synced_commits?: number; reused_commits?: number; status?: string };

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "未记录时间";
}

export default function GitHubProjectPanel({ projectId, onNotice, onError }: Props) {
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [commits, setCommits] = useState<Record<number, GitHubCommit[]>>({});
  const [repositoryInput, setRepositoryInput] = useState("");
  const [linkPreview, setLinkPreview] = useState<GitHubLinkPreview | null>(null);
  const [syncPreviews, setSyncPreviews] = useState<Record<number, SyncResult>>({});
  const [analysisPreviews, setAnalysisPreviews] = useState<Record<number, GitHubAnalysisResponse>>({});
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const result = await api.githubRepositories(projectId);
      setRepositories(result.repositories);
      const commitResults = await Promise.all(result.repositories.map(repository => api.githubCommits(projectId, repository.id)));
      setCommits(Object.fromEntries(commitResults.map(result => [result.repository.id, result.commits])));
    } catch (error) {
      onError(getApiErrorMessage(error));
    }
  }

  useEffect(() => { void load(); }, [projectId]);

  async function previewLink() {
    if (!repositoryInput.trim()) return;
    setBusy("link");
    try { setLinkPreview(await api.linkGitHubRepository(projectId, repositoryInput.trim(), false)); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  async function confirmLink() {
    setBusy("link-confirm");
    try { await api.linkGitHubRepository(projectId, repositoryInput.trim(), true); setLinkPreview(null); setRepositoryInput(""); await load(); onNotice("GitHub 仓库已关联。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  async function previewSync(repository: GitHubRepository) {
    setBusy(`sync-${repository.id}`);
    try { const result = await api.syncGitHubRepository(projectId, repository.id, false); setSyncPreviews(current => ({ ...current, [repository.id]: result })); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  async function confirmSync(repository: GitHubRepository) {
    setBusy(`sync-confirm-${repository.id}`);
    try { await api.syncGitHubRepository(projectId, repository.id, true); setSyncPreviews(current => { const next = { ...current }; delete next[repository.id]; return next; }); await load(); onNotice(`已同步 ${repository.full_name} 的提交元数据。`); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  async function previewAnalysis(commit: GitHubCommit) {
    setBusy(`analysis-${commit.id}`);
    try { const result = await api.analyzeGitHubCommit(projectId, commit.id, false); setAnalysisPreviews(current => ({ ...current, [commit.id]: result })); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  async function confirmAnalysis(commit: GitHubCommit) {
    setBusy(`analysis-confirm-${commit.id}`);
    try { await api.analyzeGitHubCommit(projectId, commit.id, true); setAnalysisPreviews(current => { const next = { ...current }; delete next[commit.id]; return next; }); await load(); onNotice("提交学习分析已保存。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(null); }
  }

  return <section className="github-project-panel">
    <div className="sf-surface-header">
      <div><h3 className="sf-section-title">GitHub 提交分析</h3><p className="sf-surface-description">绑定公开或服务端 Token 可访问的仓库，提取提交证据</p></div>
      <span className="sf-surface-metadata">{repositories.length} 个仓库</span>
    </div>
    <div className="github-policy sf-notice-surface"><strong>数据边界</strong><span>仅保存仓库、提交、文件名和行数统计；不会保存源码或 patch，不会修改 GitHub。Token 只读取服务端配置。</span></div>
    <div className="github-link-form">
      <input aria-label="GitHub 仓库" value={repositoryInput} onChange={event => setRepositoryInput(event.target.value)} placeholder="owner/repository" />
      <button className="primary-button" type="button" disabled={!repositoryInput.trim() || busy !== null} onClick={() => void previewLink()}>{busy === "link" ? "读取中…" : "预览关联"}</button>
    </div>
    {linkPreview && <div className="github-preview sf-utility-surface"><strong>仓库关联预览</strong><p>{linkPreview.repository.full_name} · {linkPreview.repository.private ? "私有" : "公开"} · 默认分支 {linkPreview.repository.default_branch ?? "未知"}</p><p>{linkPreview.warning}</p><div className="button-row"><button className="primary-button" type="button" disabled={busy !== null} onClick={() => void confirmLink()}>{busy === "link-confirm" ? "保存中…" : "确认关联"}</button><button className="ghost-button" type="button" onClick={() => setLinkPreview(null)}>取消</button></div></div>}
    {repositories.length ? <div className="github-repository-list">{repositories.map(repository => {
      const repositoryCommits = commits[repository.id] ?? [];
      const syncPreview = syncPreviews[repository.id];
      return <article className="github-repository" key={repository.id}>
        <div className="github-repository-header"><div><strong><a href={repository.html_url} target="_blank" rel="noreferrer">{repository.full_name}</a></strong><small>{repository.private ? "私有仓库" : "公开仓库"} · {repository.commit_count} 条已导入提交 · {repository.last_sync_at ? `上次同步 ${formatDate(repository.last_sync_at)}` : "尚未同步"}</small></div><button className="ghost-button" type="button" disabled={busy !== null} onClick={() => void previewSync(repository)}>{busy === `sync-${repository.id}` ? "读取中…" : "预览同步"}</button></div>
        {syncPreview && <div className="github-preview sf-utility-surface"><strong>提交同步预览</strong><p>GitHub 返回 {syncPreview.fetched_commits} 条提交，其中 {syncPreview.new_commits} 条是新增元数据。</p><p>{syncPreview.warning}</p><div className="github-commit-preview">{syncPreview.commits.slice(0, 8).map(commit => <span key={commit.sha}>{commit.short_sha} · {String(commit.message ?? "").split("\n")[0]}</span>)}</div><div className="button-row"><button className="primary-button" type="button" disabled={busy !== null} onClick={() => void confirmSync(repository)}>{busy === `sync-confirm-${repository.id}` ? "同步中…" : "确认同步"}</button><button className="ghost-button" type="button" onClick={() => setSyncPreviews(current => { const next = { ...current }; delete next[repository.id]; return next; })}>取消</button></div></div>}
        {repositoryCommits.length ? <div className="github-commit-list">{repositoryCommits.map(commit => {
          const analysisPreview = analysisPreviews[commit.id];
          return <div className="github-commit" key={commit.id}><div className="github-commit-header"><div><strong>{commit.message.split("\n")[0] || "无提交说明"}</strong><small>{commit.short_sha} · {commit.author_name || commit.author_login || "未知作者"} · {formatDate(commit.committed_at)}</small></div><span>+{commit.additions} / -{commit.deletions} · {commit.changed_files} 文件</span></div><div className="github-commit-files">{commit.files.slice(0, 5).map(file => <span key={file.filename}>{file.status} · {file.filename}</span>)}</div>{commit.analysis_confirmed ? <div className="github-analysis github-analysis-saved"><strong>已保存学习分析</strong><p>{commit.analysis.summary}</p><small>{commit.analysis.learning_points.join("；") || "暂无额外学习要点"}</small></div> : <button className="text-button" type="button" disabled={busy !== null} onClick={() => void previewAnalysis(commit)}>{busy === `analysis-${commit.id}` ? "分析中…" : "预览学习分析"}</button>}{analysisPreview && <div className="github-preview sf-utility-surface"><strong>学习分析预览</strong><p>{analysisPreview.analysis.summary}</p><p>改动领域：{analysisPreview.analysis.areas.join("、") || "未识别"} · 置信度 {Math.round(analysisPreview.analysis.confidence * 100)}%</p><div className="github-analysis-points">{analysisPreview.analysis.learning_points.map(point => <span key={point}>{point}</span>)}{analysisPreview.analysis.recommendations.map(point => <span key={point}>建议：{point}</span>)}</div><p>{analysisPreview.warning}</p><div className="button-row"><button className="primary-button" type="button" disabled={busy !== null} onClick={() => void confirmAnalysis(commit)}>{busy === `analysis-confirm-${commit.id}` ? "保存中…" : "确认保存分析"}</button><button className="ghost-button" type="button" onClick={() => setAnalysisPreviews(current => { const next = { ...current }; delete next[commit.id]; return next; })}>取消</button></div></div>}</div>;
        })}</div> : <div className="empty"><p>尚未导入提交。先预览并确认一次同步。</p></div>}
      </article>;
    })}</div> : <div className="empty"><p>还没有关联 GitHub 仓库。</p></div>}
  </section>;
}
