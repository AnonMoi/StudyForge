import { useEffect, useState } from "react";
import type { SetupStatus } from "./types";
import SettingsWorkspace from "./SettingsWorkspace";
import UserProfileWorkspace from "./UserProfileWorkspace";
import "./setup-center.css";

type Props = {
  setup: SetupStatus | null;
  onSetupChange: (setup: SetupStatus) => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
  onNavigate: (view: string) => void;
};

export default function SetupCenterWorkspace({ setup, onSetupChange, onNotice, onError, onNavigate }: Props) {
  const [guidedSetup, setGuidedSetup] = useState(Boolean(setup?.requires_onboarding));

  useEffect(() => {
    if (setup?.requires_onboarding) setGuidedSetup(true);
  }, [setup?.requires_onboarding]);

  const profileState = setup?.profile_confirmed ? "已确认" : "待确认";
  const baselineState = setup?.first_plan_generated ? "已建立" : "待建立";
  const setupComplete = Boolean(setup?.completed);

  return <div className="setup-center">
    <nav className="setup-jump-nav" aria-label="初始化设置分区">
      <a href="#learning-profile">学习画像</a>
      <a href="#model-routing">模型与路由</a>
      <a href="#usage-limits">使用限制</a>
      <a href="#advanced-settings">高级设置</a>
      <a href="#encrypted-sync">加密同步</a>
    </nav>

    <section className={`setup-status-line sf-notice-surface ${setupComplete ? "sf-notice-surface--success" : "sf-notice-surface--warning"}`} aria-label="初始化状态摘要">
      <div><span>学习画像</span><strong>{profileState}</strong></div>
      <div><span>首版学习主线</span><strong>{baselineState}</strong></div>
      <div><span>授权资料目录</span><strong>{setup?.authorized_directory_count ?? 0} 个</strong></div>
      <p>资料默认留在本地；目录访问、云端发送与写入都需要显式授权。</p>
    </section>

    <div id="learning-profile" className="setup-anchor-section">
      <UserProfileWorkspace
        onboarding={guidedSetup}
        onNotice={onNotice}
        onError={onError}
        onInitialized={onSetupChange}
        onFinished={status => { onSetupChange(status); setGuidedSetup(false); }}
      />
    </div>

    <div id="model-routing" className="setup-anchor-section">
      <SettingsWorkspace onNotice={onNotice} onError={onError} />
    </div>

    <footer className="setup-center-footer">
      <div><strong>资料目录单独管理</strong><p>目录扫描、权限和导入报告仍在文件导入工作区处理。</p></div>
      <button type="button" className="text-button" onClick={() => onNavigate("imports")}>前往文件导入</button>
    </footer>
  </div>;
}
