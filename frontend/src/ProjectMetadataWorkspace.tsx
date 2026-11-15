import { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { AuthorizedDirectory, Project } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function ProjectMetadataWorkspace({ onNotice, onError }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [directories, setDirectories] = useState<AuthorizedDirectory[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [path, setPath] = useState("");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [technologies, setTechnologies] = useState("");
  const [directoryId, setDirectoryId] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [projectData, directoryData] = await Promise.all([api.projects(), api.authorizedDirectories()]);
      setProjects(projectData);
      setDirectories(directoryData.filter(item => item.active));
      if (selectedId === null && projectData[0]) selectProject(projectData[0], projectData, directoryData);
    } catch (error) { onError(getApiErrorMessage(error)); }
  }

  useEffect(() => { void load(); }, []);

  function selectProject(project: Project, projectData = projects, directoryData = directories) {
    setSelectedId(project.id);
    setPath(project.path ?? "");
    setRepositoryUrl(project.repository_url ?? "");
    setTechnologies((project.technologies ?? []).join(", "));
    setDirectoryId(project.authorized_directory_id ? String(project.authorized_directory_id) : "");
    if (projectData.length === 0 || directoryData.length === 0) return;
  }

  async function save() {
    if (selectedId === null) return;
    setBusy(true);
    try {
      await api.updateProject(selectedId, {
        path: path.trim(),
        repository_url: repositoryUrl.trim(),
        technologies: technologies.split(",").map(item => item.trim()).filter(Boolean),
        authorized_directory_id: directoryId ? Number(directoryId) : null,
      });
      await load();
      onNotice("项目路径、仓库和技术栈已保存。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  const selected = projects.find(project => project.id === selectedId) ?? null;
  return <section className="project-metadata-workspace sf-open-section"><div className="sf-surface-header"><div><h3 className="sf-section-title">项目元数据</h3><p className="sf-surface-description">补充本地路径、仓库、技术栈和授权目录，便于项目证据追踪。</p></div><span className="sf-surface-metadata">{projects.length} 个项目</span></div>{projects.length ? <div className="stack-form"><label>选择项目<select aria-label="项目元数据选择" value={selectedId ?? ""} onChange={event => { const project = projects.find(item => item.id === Number(event.target.value)); if (project) selectProject(project); }}>{projects.map(project => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label><label>本地项目路径<input aria-label="项目元数据路径" value={path} onChange={event => setPath(event.target.value)} placeholder="可选的本地项目目录" /></label><label>仓库地址<input aria-label="项目元数据仓库地址" value={repositoryUrl} onChange={event => setRepositoryUrl(event.target.value)} placeholder="例如 https://github.com/owner/repository" /></label><label>技术栈<input aria-label="项目元数据技术栈" value={technologies} onChange={event => setTechnologies(event.target.value)} placeholder="用逗号分隔，例如 Python, FastAPI, SQLite" /></label><label>授权目录<select aria-label="项目元数据授权目录" value={directoryId} onChange={event => setDirectoryId(event.target.value)}><option value="">不关联授权目录</option>{directories.map(directory => <option key={directory.id} value={directory.id}>{directory.label || directory.path}</option>)}</select></label><small>{selected?.authorized_directory_id ? "项目已关联一个授权目录；撤销目录后不能继续保存该关联。" : "关联目录不会自动授权，目录权限仍由文件导入模块独立管理。"}</small><button type="button" className="primary-button" disabled={busy || selectedId === null} onClick={() => void save()}>{busy ? "保存中…" : "保存项目元数据"}</button></div> : <div className="empty"><p>先创建一个项目，再补充项目元数据。</p></div>}</section>;
}
