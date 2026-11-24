"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";

import { apiRequest, apiBaseUrl } from "@/lib/api";

type Section = "overview" | "profile" | "jobs" | "companies" | "recruiters" | "campaigns" | "inbox" | "agents" | "analytics" | "integrations";
type User = { id: string; email: string; created_at: string };
type Job = { id: string; title: string; company_name: string; location: string | null; version: number };
type Recruiter = { id: string; full_name: string; title: string; company_name: string; location: string | null; profile_url: string | null; sources: Array<{ source_url: string; source_title: string; captured_at: string }> };
type Campaign = { id: string; name: string; status: string; version: number; recipient_count: number; updated_at: string };
type OutreachDraft = { id: string; recruiter_id: string; job_id: string; version: number; email: { subject: string; body: string }; tone: string; created_at: string };
type Company = { company_id: string; company_name: string; latest_version: number; updated_at: string };
type Category = "positive_interest" | "request_information" | "referral" | "not_interested" | "out_of_office" | "automated" | "unclear";
type Classification = { category: Category; confidence: number; summary: string; urgency: string; suggested_next_step: string; evidence_quotes: string[] };
type Message = { provider_message_id: string; provider_thread_id: string; sender: string | null; recipients: string[]; subject: string | null; received_at: string | null; snippet: string; body_text: string; labels: string[]; classification: Classification | null; feedback_category: Category | null };
type InboxSummary = { total_messages: number; classified_messages: number; unclassified_messages: number; feedback_count: number; category_counts: Partial<Record<Category, number>>; corrected_category_counts: Partial<Record<Category, number>> };
type Agent = { id: string; name: string; purpose: string; tools: string[]; permissions: string[]; context_requirements: string[]; model_task: string; prompt_version: string; evaluation_metrics: string[] };
type Integration = { configured: boolean; connected: boolean | null; message: string };
type GmailStatus = { configured: boolean; connected: boolean; email: string | null; message: string };
type Profile = { id: string; user_id: string; version: number; full_name: string; headline: string | null; summary: string | null; target_titles: string[]; target_locations: string[]; skills: Array<{ id: string; name: string; proficiency: string | null; years_experience: number | null }>; experiences: Array<{ id: string; employer: string; title: string; location: string | null; description: string | null; start_date: string; end_date: string | null; currently_employed: boolean }>; education: Array<{ id: string; institution: string; credential: string; field_of_study: string | null; start_year: number | null; end_year: number | null }> };
type RunStarted = { run_id: string };

const navigation: Array<{ id: Section; label: string; icon: string; group: string }> = [
  { id: "overview", label: "Overview", icon: "analytics", group: "Workspace" },
  { id: "profile", label: "My profile", icon: "profile", group: "Workspace" },
  { id: "jobs", label: "Job intelligence", icon: "jobs", group: "Intelligence" },
  { id: "companies", label: "Company research", icon: "company", group: "Intelligence" },
  { id: "recruiters", label: "Recruiter discovery", icon: "recruiter", group: "Intelligence" },
  { id: "campaigns", label: "Campaigns", icon: "campaign", group: "Engagement" },
  { id: "inbox", label: "Inbox intelligence", icon: "inbox", group: "Engagement" },
  { id: "agents", label: "Agent directory", icon: "agents", group: "Platform" },
  { id: "analytics", label: "Analytics", icon: "analytics", group: "Platform" },
  { id: "integrations", label: "Integrations", icon: "company", group: "Platform" },
];

const categories: Category[] = ["positive_interest", "request_information", "referral", "not_interested", "out_of_office", "automated", "unclear"];
const categoryLabels: Record<Category, string> = {
  positive_interest: "Positive interest",
  request_information: "Information requested",
  referral: "Referral",
  not_interested: "Not interested",
  out_of_office: "Out of office",
  automated: "Automated",
  unclear: "Needs review",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function AppIcon({ name, size = 19 }: { name: string; size?: number }) {
  return <Image src={`/brand/icons/${name}.svg`} alt="" width={size} height={size} aria-hidden="true" />;
}

export function CareerReachWorkspace() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [recruiters, setRecruiters] = useState<Recruiter[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inboxSummary, setInboxSummary] = useState<InboxSummary | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [researchIntegration, setResearchIntegration] = useState<Integration | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [runIds, setRunIds] = useState<string[]>([]);

  const loadData = useCallback(async (accessToken: string) => {
    const load = async <T,>(path: string, setter: (value: T) => void) => {
      try {
        setter(await apiRequest<T>(path, accessToken));
      } catch (error) {
        if (path === "/profile" && errorMessage(error).toLowerCase().includes("not found")) {
          setter(null as T);
        } else {
          setNotice(errorMessage(error));
        }
      }
    };
    await Promise.all([
      load<User>("/auth/me", setUser),
      load<Profile>("/profile", setProfile),
      load<Job[]>("/jobs", setJobs),
      load<Recruiter[]>("/recruiters", setRecruiters),
      load<Campaign[]>("/campaigns", setCampaigns),
      load<Company[]>("/companies/research", setCompanies),
      load<Message[]>("/inbox/messages", setMessages),
      load<InboxSummary>("/inbox/summary", setInboxSummary),
      load<Agent[]>("/agents", setAgents),
      load<GmailStatus>("/integrations/google-mail", setGmail),
      load<Integration[]>("/integrations", (items) => setResearchIntegration(items[0] ?? null)),
    ]);
  }, []);

  useEffect(() => {
    if (token) void loadData(token);
  }, [loadData, token]);

  const filteredJobs = useMemo(() => jobs.filter((job) => `${job.title} ${job.company_name} ${job.location ?? ""}`.toLowerCase().includes(query.toLowerCase())), [jobs, query]);
  const filteredRecruiters = useMemo(() => recruiters.filter((item) => `${item.full_name} ${item.title} ${item.company_name}`.toLowerCase().includes(query.toLowerCase())), [recruiters, query]);
  const filteredMessages = useMemo(() => messages.filter((item) => `${item.sender ?? ""} ${item.subject ?? ""} ${item.snippet}`.toLowerCase().includes(query.toLowerCase())), [messages, query]);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      if (authMode === "register") {
        await apiRequest<User>("/auth/register", null, {
          method: "POST",
          body: JSON.stringify({ email: authEmail, password: authPassword }),
        });
      }
      const session = await apiRequest<{ access_token: string }>("/auth/token", null, {
        method: "POST",
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      });
      setToken(session.access_token);
      setNotice("You’re signed in. Your workspace is loading from CareerReach AI.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    if (token) await apiRequest<void>("/auth/logout", token, { method: "POST" }).catch(() => undefined);
    setToken(null);
    setUser(null);
    setNotice("You’ve signed out.");
  }

  async function runAction(action: () => Promise<string>) {
    setBusy(true);
    setNotice("");
    try {
      const message = await action();
      setNotice(message);
      if (token) await loadData(token);
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function syncGmail() {
    if (!token) throw new Error("Sign in before syncing Gmail.");
    await apiRequest("/integrations/google-mail/sync", token, { method: "POST" });
    await loadData(token);
    return "Gmail sync completed.";
  }

  async function classifyInbox() {
    if (!token) throw new Error("Sign in before classifying inbox messages.");
    const run = await apiRequest<RunStarted>("/inbox/classify?limit=20", token, { method: "POST" });
    setRunIds((current) => [run.run_id, ...current].slice(0, 5));
    return `Inbox classification queued as workflow ${run.run_id}.`;
  }

  async function submitFeedback(message: Message, category: Category) {
    if (!token) throw new Error("Sign in before saving inbox feedback.");
    await apiRequest(`/inbox/messages/${encodeURIComponent(message.provider_message_id)}/feedback`, token, {
      method: "POST",
      body: JSON.stringify({ category }),
    });
    await loadData(token);
    return "Your correction was saved and will inform inbox quality metrics.";
  }

  if (!token) {
    return (
      <main className="auth-layout">
        <section className="auth-story">
          <Image src="/brand/careerreach-primary.svg" alt="CareerReach AI" width={260} height={72} priority unoptimized />
          <div className="auth-story-copy">
            <span className="eyebrow light">Career clarity, with context</span>
            <h1>Make your next move with a little more signal.</h1>
            <p>Bring your profile, research, outreach and conversations into one evidence-led workspace.</p>
          </div>
          <div className="auth-story-foot"><span className="pulse-dot" /> Private by design · Your data stays in your workspace</div>
        </section>
        <section className="auth-panel">
          <div className="auth-mobile-logo"><Image src="/brand/careerreach-primary.svg" alt="CareerReach AI" width={220} height={61} unoptimized /></div>
          <div className="auth-card">
            <span className="eyebrow">Your workspace</span>
            <h2>{authMode === "login" ? "Welcome back" : "Create your account"}</h2>
            <p className="muted">Sign in to continue your career workspace.</p>
            <form onSubmit={authenticate} className="form-stack">
              <label>Email address<input type="email" autoComplete="email" required value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} /></label>
              <label>Password<input type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={12} required value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} /></label>
              <button className="button button-primary full-width" disabled={busy}>{busy ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"}<span aria-hidden="true">→</span></button>
            </form>
            <p className="auth-switch">{authMode === "login" ? "New to CareerReach?" : "Already have an account?"} <button className="text-button" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setNotice(""); }}>{authMode === "login" ? "Create an account" : "Sign in"}</button></p>
            {notice && <p className="notice" role="status">{notice}</p>}
            <p className="auth-api">API: {apiBaseUrl}</p>
          </div>
          <p className="auth-legal">CareerReach AI · Your next chapter, thoughtfully built.</p>
        </section>
      </main>
    );
  }

  const activeNav = navigation.find((item) => item.id === section);
  const reviewedRate = inboxSummary && inboxSummary.classified_messages > 0 ? Math.round((inboxSummary.feedback_count / inboxSummary.classified_messages) * 100) : 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup"><Image src="/brand/careerreach-mark.svg" alt="CareerReach AI" width={45} height={45} priority unoptimized /><span>CareerReach<span className="brand-ai">AI</span></span></div>
        <div className="workspace-pill"><span className="avatar">{user?.email.slice(0, 1).toUpperCase() ?? "C"}</span><span className="workspace-copy"><strong>My workspace</strong><small>{user?.email ?? "Candidate account"}</small></span><span className="caret">⌄</span></div>
        <nav className="main-nav" aria-label="Main navigation">
          {(["Workspace", "Intelligence", "Engagement", "Platform"] as const).map((group) => (
            <div className="nav-group" key={group}><span className="nav-label">{group}</span>
              {navigation.filter((item) => item.group === group).map((item) => (
                <button key={item.id} className={`nav-item ${section === item.id ? "selected" : ""}`} onClick={() => { setSection(item.id); setNotice(""); }}><AppIcon name={item.icon} /><span>{item.label}</span>{item.id === "inbox" && inboxSummary?.unclassified_messages ? <span className="nav-count">{inboxSummary.unclassified_messages}</span> : null}</button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer"><div className="connection-state"><span className={`status-dot ${gmail?.connected ? "online" : ""}`} /><span>{gmail?.connected ? "Gmail connected" : "Connect an email account"}</span></div><button className="nav-item" onClick={() => setSection("integrations")}><AppIcon name="company" /><span>Settings & integrations</span></button></div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="breadcrumbs"><span>CareerReach</span><span className="crumb-sep">/</span><strong>{activeNav?.label ?? "Overview"}</strong></div><div className="topbar-actions"><label className="search-box"><span aria-hidden="true">⌕</span><input aria-label="Search workspace" placeholder="Search this workspace" value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><button className="icon-button" aria-label="Notifications" onClick={() => setNotice("You’re all caught up.")}>♧</button><button className="user-chip" onClick={signOut}><span className="avatar small-avatar">{user?.email.slice(0, 1).toUpperCase() ?? "C"}</span><span>{user?.email.split("@")[0] ?? "Account"}</span><span className="caret">⌄</span></button></div></header>

        <div className="page-content">
          {notice && <div className="notice-banner" role="status"><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
          {section === "overview" && <Overview user={user} profile={profile} jobs={jobs} recruiters={recruiters} campaigns={campaigns} inboxSummary={inboxSummary} gmail={gmail} research={researchIntegration} setSection={setSection} />}
          {section === "profile" && <ProfilePanel key={profile?.version ?? "new"} profile={profile} token={token} onSaved={() => token && void loadData(token)} onNotice={setNotice} />}
          {section === "jobs" && <JobsPanel jobs={filteredJobs} token={token} onSaved={() => token && void loadData(token)} onNotice={setNotice} />}
          {section === "companies" && <CompaniesPanel companies={companies} token={token} onSaved={() => token && void loadData(token)} onNotice={setNotice} />}
          {section === "recruiters" && <RecruitersPanel recruiters={filteredRecruiters} token={token} onSaved={() => token && void loadData(token)} onNotice={setNotice} />}
          {section === "campaigns" && <CampaignsPanel campaigns={campaigns} recruiters={recruiters} jobs={jobs} token={token} busy={busy} onRefresh={() => token && void loadData(token)} onNotice={setNotice} onBusy={setBusy} />}
          {section === "inbox" && <InboxPanel messages={filteredMessages} summary={inboxSummary} busy={busy} onSync={() => void runAction(syncGmail)} onClassify={() => void runAction(classifyInbox)} onFeedback={(message, category) => void runAction(() => submitFeedback(message, category))} />}
          {section === "agents" && <AgentPanel agents={agents} runIds={runIds} />}
          {section === "analytics" && <AnalyticsPanel jobs={jobs} recruiters={recruiters} campaigns={campaigns} summary={inboxSummary} reviewedRate={reviewedRate} />}
          {section === "integrations" && <IntegrationsPanel gmail={gmail} research={researchIntegration} token={token} busy={busy} onRefresh={() => token && void loadData(token)} onNotice={setNotice} />}
        </div>
        <footer className="page-footer"><span>CareerReach AI · Evidence before action</span><span>Workspace data is private to your account</span></footer>
      </main>
    </div>
  );
}

function PageHeading({ eyebrow, title, subtitle, right }: { eyebrow: string; title: string; subtitle: string; right?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div>{right}</div>;
}

function Overview({ user, profile, jobs, recruiters, campaigns, inboxSummary, gmail, research, setSection }: { user: User | null; profile: Profile | null; jobs: Job[]; recruiters: Recruiter[]; campaigns: Campaign[]; inboxSummary: InboxSummary | null; gmail: GmailStatus | null; research: Integration | null; setSection: (section: Section) => void }) {
  const firstName = user?.email.split("@")[0].split(/[._-]/)[0] ?? "there";
  return <>
    <div className="welcome-panel"><div className="welcome-copy"><span className="eyebrow light">Your career workspace</span><h1>Good to see you, {firstName}.</h1><p>Small, deliberate steps. Grounded in your experience and the opportunities ahead.</p><button className="button button-light" onClick={() => setSection("jobs")}>Explore your workspace <span>→</span></button></div><div className="welcome-mark"><span className="orbit orbit-one"/><span className="orbit orbit-two"/><span className="orbit-core"><AppIcon name="agents" size={42} /></span><span className="orbit-node node-one"/><span className="orbit-node node-two"/><span className="orbit-node node-three"/></div></div>
    <PageHeading eyebrow="Overview" title="Your next move, in view." subtitle="A live snapshot of the work and conversations in your career pipeline." />
    <div className="metric-grid"><MetricCard label="Saved jobs" value={jobs.length} detail="Roles in your workspace" icon="jobs" tint="blue" /><MetricCard label="Recruiter contacts" value={recruiters.length} detail="Sources retained with contacts" icon="recruiter" tint="teal" /><MetricCard label="Active campaigns" value={campaigns.filter((item) => ["approved", "running", "paused"].includes(item.status)).length} detail={`${campaigns.length} total campaigns`} icon="campaign" tint="violet" /><MetricCard label="Inbox to review" value={inboxSummary?.unclassified_messages ?? "—"} detail={gmail?.connected ? "Gmail sync available" : "Connect Gmail to sync"} icon="inbox" tint="amber" /></div>
    <div className="dashboard-grid"><section className="surface-card focus-card"><div className="card-heading"><div><span className="eyebrow">Suggested focus</span><h3>Build a strong foundation</h3></div><span className="status-chip">{profile ? "Profile active" : "Profile needed"}</span></div><div className="focus-step"><span className="step-index">01</span><div><strong>{profile ? "Keep your story current" : "Complete your candidate profile"}</strong><p>{profile ? `Profile version ${profile.version} is ready to support matching.` : "Add your skills and experience so matching can use your real context."}</p></div><button className="arrow-button" onClick={() => setSection("profile")} aria-label="Open profile">→</button></div><div className="focus-step"><span className="step-index">02</span><div><strong>Review researched opportunities</strong><p>{jobs.length ? `${jobs.length} job${jobs.length === 1 ? "" : "s"} saved with source details.` : "Save a job to begin an evidence-led fit analysis."}</p></div><button className="arrow-button" onClick={() => setSection("jobs")} aria-label="Open jobs">→</button></div><div className="focus-step"><span className="step-index">03</span><div><strong>Stay close to replies</strong><p>{inboxSummary ? `${inboxSummary.classified_messages} messages classified; ${inboxSummary.feedback_count} corrections captured.` : "Connect Gmail to bring replies into your workspace."}</p></div><button className="arrow-button" onClick={() => setSection("inbox")} aria-label="Open inbox">→</button></div></section><section className="surface-card activity-card"><div className="card-heading"><div><span className="eyebrow">Connected tools</span><h3>Workspace readiness</h3></div><button className="text-button" onClick={() => setSection("integrations")}>Manage</button></div><IntegrationRow icon="inbox" name="Gmail" detail={gmail?.email ?? (gmail?.configured ? "Not connected" : "Credentials needed")} connected={Boolean(gmail?.connected)} /><IntegrationRow icon="company" name="Web research" detail={research?.message ?? "Loading provider status"} connected={Boolean(research?.connected)} /><div className="agent-note"><span className="agent-note-icon"><AppIcon name="agents" /></span><div><strong>Human approval stays in control</strong><p>Campaigns require explicit review before an email is sent.</p></div></div></section></div>
  </>;
}

function MetricCard({ label, value, detail, icon, tint }: { label: string; value: string | number; detail: string; icon: string; tint: string }) {
  return <article className="metric-card"><div className={`metric-icon ${tint}`}><AppIcon name={icon} /></div><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><span className="metric-detail">{detail}</span></article>;
}

function IntegrationRow({ icon, name, detail, connected }: { icon: string; name: string; detail: string; connected: boolean }) {
  return <div className="integration-row"><span className="integration-icon"><AppIcon name={icon} /></span><span className="integration-copy"><strong>{name}</strong><small>{detail}</small></span><span className={`connection-label ${connected ? "connected" : "disconnected"}`}><i />{connected ? "Connected" : "Not connected"}</span></div>;
}

function DataList({ title, subtitle, count, action, children }: { title: string; subtitle: string; count: number; action: ReactNode; children: ReactNode }) {
  return <><PageHeading eyebrow="Workspace" title={title} subtitle={subtitle} right={action} /><section className="surface-card data-list"><div className="data-list-head"><div><strong>{count} {count === 1 ? "record" : "records"}</strong><span> · Loaded from your CareerReach account</span></div><span className="live-label"><i /> Live data</span></div>{count ? <div className="list-stack">{children}</div> : <EmptyState title="Nothing here yet" text="This view fills with real records as you use the matching CareerReach workflows." />}</section></>;
}

function CampaignsPanel({ campaigns, recruiters, jobs, token, busy, onRefresh, onNotice, onBusy }: { campaigns: Campaign[]; recruiters: Recruiter[]; jobs: Job[]; token: string | null; busy: boolean; onRefresh: () => void; onNotice: (message: string) => void; onBusy: (busy: boolean) => void }) {
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftPreview, setDraftPreview] = useState<OutreachDraft | null>(null);

  async function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const values = new FormData(event.currentTarget);
    setDraftBusy(true);
    try {
      const draft = await apiRequest<OutreachDraft>("/outreach/drafts", token, { method: "POST", body: JSON.stringify({ recruiter_id: values.get("recruiter_id"), job_id: values.get("job_id"), tone: values.get("tone"), context: values.get("context") || null }) });
      setDrafts((current) => [draft, ...current]);
      setDraftPreview(draft);
      setExpanded(false);
      onNotice("Evidence-grounded outreach draft created. Review it before adding it to a campaign.");
    } catch (error) { onNotice(errorMessage(error)); }
    finally { setDraftBusy(false); }
  }

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const values = new FormData(event.currentTarget);
    const draft = drafts.find((item) => item.id === values.get("draft_id"));
    if (!draft) { onNotice("Create a draft in this session before creating a campaign."); return; }
    onBusy(true);
    try {
      await apiRequest("/campaigns", token, { method: "POST", body: JSON.stringify({ name: values.get("name"), recipients: [{ draft_id: draft.id, recipient_email: values.get("recipient_email") }] }) });
      onNotice("Campaign created as a draft. Submit it for approval when you’re ready.");
      onRefresh();
      event.currentTarget.reset();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { onBusy(false); }
  }

  async function campaignAction(campaign: Campaign, action: string) {
    if (!token) return;
    onBusy(true);
    try {
      await apiRequest(`/campaigns/${campaign.id}/transition`, token, { method: "POST", body: JSON.stringify({ action, expected_version: campaign.version }) });
      onNotice(`Campaign ${action.replaceAll("_", " ")} action completed.`);
      onRefresh();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { onBusy(false); }
  }

  async function executeCampaign(campaign: Campaign) {
    if (!token) return;
    onBusy(true);
    try {
      const run = await apiRequest<RunStarted>(`/campaigns/${campaign.id}/execute`, token, { method: "POST" });
      onNotice(`Approved outreach is being sent through workflow ${run.run_id}.`);
      onRefresh();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { onBusy(false); }
  }

  const actionsFor = (campaign: Campaign) => {
    const actions: Array<{ label: string; action: string; style?: string }> = [];
    if (campaign.status === "draft") actions.push({ label: "Submit for approval", action: "submit", style: "button-primary" });
    if (campaign.status === "awaiting_approval") { actions.push({ label: "Approve", action: "approve", style: "button-primary" }); actions.push({ label: "Reject", action: "reject" }); }
    if (campaign.status === "approved") actions.push({ label: "Start sending", action: "execute", style: "button-primary" });
    if (campaign.status === "running") actions.push({ label: "Pause", action: "pause" });
    if (campaign.status === "paused") actions.push({ label: "Resume", action: "resume", style: "button-primary" });
    if (campaign.status === "failed") actions.push({ label: "Retry failed", action: "retry_failed", style: "button-primary" });
    if (!["completed", "cancelled"].includes(campaign.status)) actions.push({ label: "Cancel", action: "cancel" });
    return actions;
  };

  return <>
    <DataList title="Campaigns" subtitle="Review each message, submit for approval and control delivery." count={campaigns.length} action={<button className="button button-primary" onClick={() => setExpanded((value) => !value)}>{expanded ? "Close draft form" : "+ Draft outreach"}</button>}>
      {campaigns.map((campaign) => <article className="list-card campaign-row" key={campaign.id}><span className="list-icon"><AppIcon name="campaign" /></span><div className="list-main"><strong>{campaign.name}</strong><span>{campaign.recipient_count} recipients · Version {campaign.version} · Updated {new Date(campaign.updated_at).toLocaleDateString()}</span></div><span className={`status-pill status-${campaign.status}`}>{campaign.status.replaceAll("_", " ")}</span><div className="campaign-actions">{actionsFor(campaign).map(({ label, action, style }) => <button key={action} className={`button button-small ${style ?? "button-secondary"}`} disabled={busy} onClick={() => action === "execute" ? void executeCampaign(campaign) : void campaignAction(campaign, action)}>{label}</button>)}</div></article>)}
    </DataList>
    {expanded && <section className="surface-card composer-card"><div className="card-heading"><div><span className="eyebrow">Review before sending</span><h3>Create evidence-grounded outreach</h3></div></div>
      {drafts.length === 0 && <form className="workspace-form" onSubmit={createDraft}><label className="field-label">Recruiter<select name="recruiter_id" required defaultValue=""><option value="" disabled>Select a discovered contact</option>{recruiters.map((item) => <option key={item.id} value={item.id}>{item.full_name} · {item.company_name}</option>)}</select></label><label className="field-label">Saved job<select name="job_id" required defaultValue=""><option value="" disabled>Select a job</option>{jobs.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.company_name}</option>)}</select></label><label className="field-label">Tone<select name="tone" defaultValue="warm"><option value="warm">Warm</option><option value="direct">Direct</option><option value="formal">Formal</option></select></label><label className="field-label">Additional context<input name="context" maxLength={2000} placeholder="Optional, factual context" /></label><div className="form-actions"><span className="muted">Claims are checked against saved profile, job and recruiter evidence.</span><button className="button button-primary" disabled={draftBusy || !recruiters.length || !jobs.length}>{draftBusy ? "Drafting…" : "Create draft"}</button></div></form>}
      {draftPreview && <div className="draft-preview"><div className="card-heading"><div><span className="eyebrow">Draft preview · {draftPreview.tone}</span><h3>{draftPreview.email.subject}</h3></div><span className="version-pill">v{draftPreview.version}</span></div><p>{draftPreview.email.body}</p><div className="form-actions"><span className="muted">Review the recipient address and message before creating the approval-gated campaign.</span></div></div>}
      {drafts.length > 0 && <form className="workspace-form campaign-create-form" onSubmit={createCampaign}><label className="field-label">Campaign name<input name="name" required maxLength={200} placeholder="e.g. Product engineering outreach" /></label><label className="field-label">Draft<select name="draft_id" required defaultValue={drafts[0].id}>{drafts.map((item) => <option key={item.id} value={item.id}>{item.email.subject} · draft v{item.version}</option>)}</select></label><label className="field-label full-span">Recipient email<input name="recipient_email" type="email" required /></label><div className="form-actions"><span className="muted">Creation does not send email. Submission and approval are separate steps.</span><button className="button button-primary" disabled={busy}>Create campaign</button></div></form>}
    </section>}
  </>;
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="empty-state"><span className="empty-orbit"><AppIcon name="agents" size={24} /></span><h3>{title}</h3><p>{text}</p></div>;
}

function ProfilePanel({ profile, token, onSaved, onNotice }: { profile: Profile | null; token: string | null; onSaved: () => void; onNotice: (message: string) => void }) {
  const [fullName, setFullName] = useState(profile?.full_name ?? "");
  const [headline, setHeadline] = useState(profile?.headline ?? "");
  const [summary, setSummary] = useState(profile?.summary ?? "");
  const [skillsText, setSkillsText] = useState(profile?.skills.map((skill) => skill.name).join(", ") ?? "");
  const [saving, setSaving] = useState(false);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setSaving(true);
    try {
      await apiRequest<Profile>("/profile", token, { method: "PUT", body: JSON.stringify({
        expected_version: profile?.version ?? null,
        full_name: fullName,
        headline: headline || null,
        summary: summary || null,
        target_titles: profile?.target_titles ?? [],
        target_locations: profile?.target_locations ?? [],
        skills: skillsText.split(",").map((name) => name.trim()).filter(Boolean).map((name) => {
          const existing = profile?.skills.find((skill) => skill.name.toLowerCase() === name.toLowerCase());
          return { name, proficiency: existing?.proficiency ?? null, years_experience: existing?.years_experience ?? null };
        }),
        experiences: profile?.experiences.map(({ employer, title, location, description, start_date, end_date, currently_employed }) => ({ employer, title, location, description, start_date, end_date, currently_employed })) ?? [],
        education: profile?.education.map(({ institution, credential, field_of_study, start_year, end_year }) => ({ institution, credential, field_of_study, start_year, end_year })) ?? [],
      }) });
      onNotice("Candidate profile saved with a new version.");
      onSaved();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { setSaving(false); }
  }
  return <><PageHeading eyebrow="Candidate intelligence" title="Your profile" subtitle="The candidate context used by research, matching and outreach workflows." /><section className="surface-card profile-card"><div className="profile-top"><span className="profile-avatar"><AppIcon name="profile" size={28} /></span><div><h2>{profile?.headline || profile?.full_name || "Candidate profile"}</h2><p>{profile ? `Profile version ${profile.version}` : "Set up the context that powers personalized workflows."}</p></div>{profile && <span className="status-chip">Current</span>}</div><form className="workspace-form" onSubmit={save}><label className="field-label">Full name<input required maxLength={200} value={fullName} onChange={(event) => setFullName(event.target.value)} /></label><label className="field-label">Headline<input maxLength={300} value={headline} onChange={(event) => setHeadline(event.target.value)} placeholder="e.g. Senior backend engineer" /></label><label className="field-label full-span">Professional summary<textarea maxLength={10000} value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="A concise, factual overview of your experience." /></label><label className="field-label full-span">Skills<input value={skillsText} onChange={(event) => setSkillsText(event.target.value)} placeholder="Python, PostgreSQL, distributed systems" /><small>Separate skills with commas. Existing proficiency details are preserved.</small></label><div className="form-actions"><span className="muted">Only the skills entered above are saved.</span><button className="button button-primary" disabled={saving}>{saving ? "Saving…" : profile ? "Save profile" : "Create profile"}</button></div></form></section></>;
}

function JobsPanel({ jobs, token, onSaved, onNotice }: { jobs: Job[]; token: string | null; onSaved: () => void; onNotice: (message: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const values = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await apiRequest("/jobs", token, { method: "POST", body: JSON.stringify({ title: values.get("title"), company_name: values.get("company"), location: values.get("location") || null, source_url: values.get("source_url") || null, description: values.get("description") }) });
      setExpanded(false);
      onNotice("Job saved and analyzed from the supplied description.");
      onSaved();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { setSaving(false); }
  }
  const action = <button className="button button-primary" onClick={() => setExpanded((value) => !value)}>{expanded ? "Close form" : "+ Analyze a job"}</button>;
  return <><DataList title="Job intelligence" subtitle="Roles you’ve saved and analyzed from source material." count={jobs.length} action={action}>{jobs.map((job) => <article className="list-card" key={job.id}><span className="list-icon"><AppIcon name="jobs" /></span><div className="list-main"><strong>{job.title}</strong><span>{job.company_name} · {job.location ?? "Location not specified"}</span></div><span className="version-pill">v{job.version}</span></article>)}</DataList>{expanded && <section className="surface-card composer-card"><div className="card-heading"><div><span className="eyebrow">Source-grounded analysis</span><h3>Add a job description</h3></div></div><form className="workspace-form" onSubmit={submit}><label className="field-label">Job title<input name="title" required maxLength={200} /></label><label className="field-label">Company<input name="company" required maxLength={200} /></label><label className="field-label">Location<input name="location" maxLength={200} /></label><label className="field-label">Source URL<input name="source_url" type="url" /></label><label className="field-label full-span">Job description<textarea name="description" required minLength={100} maxLength={50000} /></label><div className="form-actions"><span className="muted">The analysis uses only this description as evidence.</span><button className="button button-primary" disabled={saving}>{saving ? "Analyzing…" : "Analyze and save"}</button></div></form></section>}</>;
}

function CompaniesPanel({ companies, token, onSaved, onNotice }: { companies: Company[]; token: string | null; onSaved: () => void; onNotice: (message: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const values = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const research = await apiRequest<{ company_name: string; analysis: { summary: string }; sources: unknown[] }>("/companies/research", token, { method: "POST", body: JSON.stringify({ company_name: values.get("company_name"), query: values.get("query") || null, result_count: 6 }) });
      setExpanded(false);
      onNotice(`Research for ${research.company_name} completed from ${research.sources.length} source records.`);
      onSaved();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { setSaving(false); }
  }
  return <><DataList title="Company research" subtitle="Evidence-backed company context from real web sources." count={companies.length} action={<button className="button button-primary" onClick={() => setExpanded((value) => !value)}>{expanded ? "Close form" : "+ Research a company"}</button>}>{companies.map((company) => <article className="list-card" key={company.company_id}><span className="list-icon"><AppIcon name="company" /></span><div className="list-main"><strong>{company.company_name}</strong><span>Updated {new Date(company.updated_at).toLocaleDateString()}</span></div><span className="version-pill">v{company.latest_version}</span></article>)}</DataList>{expanded && <section className="surface-card composer-card"><div className="card-heading"><div><span className="eyebrow">Live research</span><h3>Build a sourced company brief</h3></div></div><form className="workspace-form" onSubmit={submit}><label className="field-label">Company name<input name="company_name" required maxLength={200} /></label><label className="field-label">Research angle<input name="query" minLength={3} maxLength={500} placeholder="Hiring, product, market…" /></label><div className="form-actions"><span className="muted">The brief will retain source URLs and capture times.</span><button className="button button-primary" disabled={saving}>{saving ? "Researching…" : "Research company"}</button></div></form></section>}</>;
}

function RecruitersPanel({ recruiters, token, onSaved, onNotice }: { recruiters: Recruiter[]; token: string | null; onSaved: () => void; onNotice: (message: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const values = new FormData(event.currentTarget);
    setSaving(true);
    try {
      const result = await apiRequest<{ recruiters: Recruiter[] }>("/recruiters/discover", token, { method: "POST", body: JSON.stringify({ company_name: values.get("company_name"), target_role: values.get("target_role"), location: values.get("location") || null, result_count: 6 }) });
      setExpanded(false);
      onNotice(`Discovery returned ${result.recruiters.length} source-checked contacts. Review each source before outreach.`);
      onSaved();
    } catch (error) { onNotice(errorMessage(error)); }
    finally { setSaving(false); }
  }
  return <><DataList title="Recruiter discovery" subtitle="Contacts found and retained with source context." count={recruiters.length} action={<button className="button button-primary" onClick={() => setExpanded((value) => !value)}>{expanded ? "Close form" : "+ Discover contacts"}</button>}>{recruiters.map((contact) => <article className="list-card" key={contact.id}><span className="list-icon"><AppIcon name="recruiter" /></span><div className="list-main"><strong>{contact.full_name}</strong><span>{contact.title} · {contact.company_name}{contact.location ? ` · ${contact.location}` : ""}</span></div>{contact.profile_url ? <a className="subtle-link" href={contact.profile_url} target="_blank" rel="noreferrer">Profile ↗</a> : contact.sources[0] && <a className="subtle-link" href={contact.sources[0].source_url} target="_blank" rel="noreferrer">Source ↗</a>}</article>)}</DataList>{expanded && <section className="surface-card composer-card"><div className="card-heading"><div><span className="eyebrow">Contact discovery</span><h3>Find relevant recruiters</h3></div></div><form className="workspace-form" onSubmit={submit}><label className="field-label">Company<input name="company_name" required maxLength={200} /></label><label className="field-label">Target role<input name="target_role" required maxLength={200} /></label><label className="field-label">Location<input name="location" maxLength={200} /></label><div className="form-actions"><span className="muted">Only contacts supported by source evidence are retained.</span><button className="button button-primary" disabled={saving}>{saving ? "Searching…" : "Discover contacts"}</button></div></form></section>}</>;
}

function InboxPanel({ messages, summary, busy, onSync, onClassify, onFeedback }: { messages: Message[]; summary: InboxSummary | null; busy: boolean; onSync: () => void; onClassify: () => void; onFeedback: (message: Message, category: Category) => void }) {
  const [selected, setSelected] = useState<Record<string, Category>>({});
  return <><PageHeading eyebrow="Inbox intelligence" title="Conversations, with context." subtitle="Classify replies, inspect the evidence and correct labels to improve feedback quality." right={<div className="heading-actions"><button className="button button-secondary" disabled={busy} onClick={onSync}>↻ Sync Gmail</button><button className="button button-primary" disabled={busy} onClick={onClassify}><AppIcon name="agents" size={16} /> Classify replies</button></div>} /><div className="inbox-stat-strip">{[
    ["Messages", summary?.total_messages ?? 0], ["Classified", summary?.classified_messages ?? 0], ["Need classification", summary?.unclassified_messages ?? 0], ["Human corrections", summary?.feedback_count ?? 0],
  ].map(([label, value]) => <div className="inbox-stat" key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="inbox-list">{messages.length ? messages.map((message) => {
    const category = message.feedback_category ?? message.classification?.category;
    return <article className="surface-card message-card" key={message.provider_message_id}><div className="message-main"><div className="message-avatar">{(message.sender ?? "?").slice(0, 1).toUpperCase()}</div><div className="message-body"><div className="message-heading"><div><strong>{message.sender ?? "Unknown sender"}</strong><span>{message.subject || "No subject"}</span></div><span className="message-date">{message.received_at ? new Date(message.received_at).toLocaleDateString() : "Date unavailable"}</span></div><p className="message-snippet">{message.classification?.summary ?? message.snippet}</p>{message.classification && <><div className="classification-meta"><span className={`category-chip category-${message.classification.category}`}>{categoryLabels[message.classification.category]}</span><span>{Math.round(message.classification.confidence * 100)}% confidence</span><span>{message.classification.urgency} priority</span></div><div className="evidence-box"><span className="evidence-mark">“</span><span>{message.classification.evidence_quotes.join(" · ")}</span></div><p className="suggested-next">Suggested next step <strong>{message.classification.suggested_next_step}</strong></p></>}{category && message.feedback_category && <span className="feedback-saved">✓ Corrected label saved</span>}</div></div><div className="feedback-row"><label>Correct classification<select value={selected[message.provider_message_id] ?? category ?? "unclear"} onChange={(event) => setSelected((current) => ({ ...current, [message.provider_message_id]: event.target.value as Category }))}>{categories.map((item) => <option key={item} value={item}>{categoryLabels[item]}</option>)}</select></label><button className="button button-small" disabled={busy} onClick={() => onFeedback(message, selected[message.provider_message_id] ?? category ?? "unclear")}>Save feedback</button></div></article>;
  }) : <section className="surface-card empty-container"><EmptyState title="Your inbox is ready when you are" text="Connect Gmail and sync messages. CareerReach will only classify messages you’ve synced into this account." /></section>}</div></>;
}

function AgentPanel({ agents, runIds }: { agents: Agent[]; runIds: string[] }) {
  return <><PageHeading eyebrow="Agent activity centre" title="A transparent agent team." subtitle="Inspect each agent’s purpose, tools and permissions before asking it to do work." /><div className="agent-grid">{agents.map((agent) => <article className="surface-card agent-card" key={agent.id}><div className="agent-card-top"><span className="agent-icon"><AppIcon name="agents" /></span><span className="model-badge">{agent.model_task}</span></div><h3>{agent.name}</h3><p>{agent.purpose}</p><div className="agent-tags"><span>{agent.tools.length} scoped tools</span><span>{agent.permissions.length} permissions</span><span>{agent.prompt_version}</span></div><div className="agent-context"><span className="eyebrow">Context required</span><p>{agent.context_requirements.join(" · ") || "None listed"}</p></div><div className="agent-context"><span className="eyebrow">Quality signals</span><p>{agent.evaluation_metrics.join(" · ")}</p></div></article>)}</div>{runIds.length > 0 && <section className="surface-card workflow-card"><span className="eyebrow">Workflows started this session</span>{runIds.map((id) => <p key={id}><code>{id}</code> <span className="status-pill status-running">submitted</span></p>)}</section>}</>;
}

function AnalyticsPanel({ jobs, recruiters, campaigns, summary, reviewedRate }: { jobs: Job[]; recruiters: Recruiter[]; campaigns: Campaign[]; summary: InboxSummary | null; reviewedRate: number }) {
  return <><PageHeading eyebrow="Analytics" title="Progress you can inspect." subtitle="Counts are based on records currently available in your workspace; no performance is inferred." /><div className="metric-grid analytics-metrics"><MetricCard label="Jobs researched" value={jobs.length} detail="Saved job records" icon="jobs" tint="blue" /><MetricCard label="Contacts discovered" value={recruiters.length} detail="Contact records in workspace" icon="recruiter" tint="teal" /><MetricCard label="Campaigns" value={campaigns.length} detail="All campaign states" icon="campaign" tint="violet" /><MetricCard label="Inbox feedback" value={summary?.feedback_count ?? 0} detail={`${reviewedRate}% of classified messages corrected`} icon="inbox" tint="amber" /></div><section className="surface-card analytics-card"><div className="card-heading"><div><span className="eyebrow">Inbox outcomes</span><h3>Classification and feedback</h3></div><span className="live-label"><i /> Workspace totals</span></div><div className="outcome-bars">{categories.map((category) => { const value = summary?.category_counts[category] ?? 0; const max = Math.max(1, ...Object.values(summary?.category_counts ?? {})); return <div className="outcome-row" key={category}><span>{categoryLabels[category]}</span><div className="bar-track"><i style={{ width: `${Math.max(value ? 6 : 0, (value / max) * 100)}%` }} /></div><strong>{value}</strong></div>; })}</div><p className="analytics-note">Corrections are retained as labeled feedback. They are not used to retrain a model automatically.</p></section></>;
}

function IntegrationsPanel({ gmail, research, token, busy, onRefresh, onNotice }: { gmail: GmailStatus | null; research: Integration | null; token: string | null; busy: boolean; onRefresh: () => void; onNotice: (message: string) => void }) {
  async function authorizeGoogle() {
    if (!token) return;
    try {
      const data = await apiRequest<{ authorization_url: string }>("/integrations/google-mail/authorize", token);
      window.location.assign(data.authorization_url);
    } catch (error) { onNotice(errorMessage(error)); }
  }
  return <><PageHeading eyebrow="Integrations" title="Bring your tools together." subtitle="Connections are account-scoped, and external actions remain behind approval." /><div className="integration-grid"><section className="surface-card integration-card"><div className="integration-card-top"><span className="integration-icon large"><AppIcon name="inbox" size={24} /></span><span className={`connection-label ${gmail?.connected ? "connected" : "disconnected"}`}><i />{gmail?.connected ? "Connected" : "Not connected"}</span></div><h3>Google Gmail</h3><p>{gmail?.email ?? "Sync replies into your inbox and deliver approved outreach from your connected mailbox."}</p><div className="integration-permissions"><span>Granted access</span><small>Send mail · Read mail</small></div><button className="button button-primary" disabled={busy} onClick={() => void authorizeGoogle()}>{gmail?.connected ? "Reconnect Gmail" : "Connect Gmail"}</button></section><section className="surface-card integration-card"><div className="integration-card-top"><span className="integration-icon large"><AppIcon name="company" size={24} /></span><span className={`connection-label ${research?.configured ? "connected" : "disconnected"}`}><i />{research?.configured ? "Configured" : "Needs setup"}</span></div><h3>Brave Search</h3><p>{research?.message ?? "Search provider status is unavailable."}</p><div className="integration-permissions"><span>Used for</span><small>Job and company research</small></div><button className="button button-secondary" onClick={onRefresh}>Refresh status</button></section><section className="integration-note"><span className="note-shield">✳</span><div><strong>Access is scoped to your account</strong><p>OAuth credentials stay on the backend. Your browser receives only a short-lived access token held in memory for this session.</p></div></section></div></>;
}
