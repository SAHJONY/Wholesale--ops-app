'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from './campaigns.module.css';

const API_URL = '/api/backend';
const SIGN_IN = '/login?returnTo=/owner/sms-acquisition/campaigns';

type SmartList = {
  id: number;
  name: string;
  description?: string;
  filters: Record<string, unknown>;
  audience_count: number;
};

type Template = {
  id: number;
  name: string;
  body: string;
  pathway_id?: string;
  persona_id?: string;
};

type Campaign = {
  id: number;
  name: string;
  status: string;
  smart_list_id?: number;
  template_id?: number;
  audience_count: number;
  prepared_count: number;
  suppressed_count: number;
  ready_count: number;
  created_at: string;
};

type Summary = {
  smart_lists: number;
  templates: number;
  campaigns: number;
  prepared_recipients: number;
  needs_compliance: number;
};

const defaultTemplate = 'Hi {{first_name}}, this is SAHJONY. We are reaching out about {{property_address}}. Would you consider an offer? Reply STOP to opt out.';

function splitCsv(value: FormDataEntryValue | null) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean);
}

export default function CampaignManager() {
  const [summary, setSummary] = useState<Summary>({ smart_lists: 0, templates: 0, campaigns: 0, prepared_recipients: 0, needs_compliance: 0 });
  const [lists, setLists] = useState<SmartList[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string, options: RequestInit = {}) => {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer cookie-session',
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [summaryData, listData, templateData, campaignData] = await Promise.all([
        request('/sms-campaigns/summary'),
        request('/sms-campaigns/smart-lists'),
        request('/sms-campaigns/templates'),
        request('/sms-campaigns'),
      ]);
      setSummary(summaryData);
      setLists(Array.isArray(listData) ? listData : []);
      setTemplates(Array.isArray(templateData) ? templateData : []);
      setCampaigns(Array.isArray(campaignData) ? campaignData : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load SAHJONY campaigns');
    } finally { setLoading(false); }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  async function createList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      await request('/sms-campaigns/smart-lists', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'),
          description: form.get('description'),
          filters: {
            states: splitCsv(form.get('states')),
            zip_codes: splitCsv(form.get('zip_codes')),
            statuses: splitCsv(form.get('statuses')),
            sources: splitCsv(form.get('sources')),
            min_motivation: Number(form.get('min_motivation') || 0),
            min_distress: Number(form.get('min_distress') || 0),
            max_timeline_days: form.get('max_timeline_days') ? Number(form.get('max_timeline_days')) : undefined,
            has_phone: true,
          },
        }),
      });
      setNotice('Smart list created. Audience is calculated from the current SAHJONY lead workspace.');
      event.currentTarget.reset();
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create smart list'); }
    finally { setLoading(false); }
  }

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      await request('/sms-campaigns/templates', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'),
          body: form.get('body'),
          pathway_id: form.get('pathway_id'),
          persona_id: form.get('persona_id'),
        }),
      });
      setNotice('SAHJONY message template saved.');
      event.currentTarget.reset();
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create template'); }
    finally { setLoading(false); }
  }

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request('/sms-campaigns', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'),
          smart_list_id: Number(form.get('smart_list_id')),
          template_id: Number(form.get('template_id')),
        }),
      });
      setNotice(`Campaign #${result.id} created for ${result.audience_count} current matching leads. Prepare it to render and preflight each recipient.`);
      event.currentTarget.reset();
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create campaign'); }
    finally { setLoading(false); }
  }

  async function prepareCampaign(id: number) {
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request(`/sms-campaigns/${id}/prepare`, { method: 'POST', body: '{}' });
      setNotice(`Campaign #${id}: ${result.prepared_count} prepared, ${result.suppressed_count} suppressed, ${result.needs_compliance} awaiting recipient-level compliance.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to prepare campaign'); }
    finally { setLoading(false); }
  }

  const totalAudience = useMemo(() => lists.reduce((sum, item) => sum + Number(item.audience_count || 0), 0), [lists]);

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY AI ACQUISITION</span>
        <h1>Campaign Manager</h1>
        <p>Build proprietary seller audiences, personalized messages and Bland-powered acquisition campaigns. Every recipient remains individually gated by suppression, compliance and owner approval before dispatch.</p>
      </div>
      <nav>
        <a href="/owner/sms-acquisition">AI SMS Acquisition</a>
        <a href="/owner/communications">Communication Center</a>
        <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </nav>
    </header>

    {notice && <div className={styles.notice}>{notice}</div>}
    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Smart lists</span><strong>{summary.smart_lists}</strong><small>{totalAudience} current list matches</small></article>
      <article><span>Templates</span><strong>{summary.templates}</strong><small>SAHJONY-owned messaging assets</small></article>
      <article><span>Campaigns</span><strong>{summary.campaigns}</strong><small>Bland transport</small></article>
      <article><span>Compliance queue</span><strong>{summary.needs_compliance}</strong><small>Prepared, not authorized to send</small></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}>
        <span className={styles.eyebrow}>1 · AUDIENCE</span><h2>Create smart list</h2>
        <form onSubmit={createList}>
          <input name="name" placeholder="e.g. Harris County pre-foreclosure 30-day" required />
          <textarea name="description" placeholder="Audience purpose" rows={2} />
          <input name="states" placeholder="States: TX, GA" />
          <input name="zip_codes" placeholder="ZIPs: 77021, 77033" />
          <input name="statuses" placeholder="Statuses: new, contacting, nurture" />
          <input name="sources" placeholder="Sources: foreclosure, probate, code_violation" />
          <div className={styles.inline}>
            <input name="min_motivation" type="number" min="0" max="100" placeholder="Min motivation" />
            <input name="min_distress" type="number" min="0" max="100" placeholder="Min distress" />
          </div>
          <input name="max_timeline_days" type="number" min="1" placeholder="Max seller timeline days" />
          <button disabled={loading}>Create smart list</button>
        </form>
      </article>

      <article className={styles.card}>
        <span className={styles.eyebrow}>2 · MESSAGE</span><h2>Create template</h2>
        <form onSubmit={createTemplate}>
          <input name="name" placeholder="Template name" required />
          <textarea name="body" defaultValue={defaultTemplate} rows={7} required />
          <div className={styles.help}>Merge fields: {'{{first_name}}'} · {'{{seller_name}}'} · {'{{property_address}}'} · {'{{city}}'} · {'{{state}}'} · {'{{zip_code}}'} · {'{{company}}'} · {'{{source}}'} · {'{{asking_price}}'} · {'{{arv}}'} · {'{{mao}}'}</div>
          <input name="pathway_id" placeholder="Optional Bland Pathway ID" />
          <input name="persona_id" placeholder="Optional Bland Persona ID" />
          <button disabled={loading}>Save template</button>
        </form>
      </article>

      <article className={styles.card}>
        <span className={styles.eyebrow}>3 · CAMPAIGN</span><h2>Build campaign</h2>
        <form onSubmit={createCampaign}>
          <input name="name" placeholder="Campaign name" required />
          <select name="smart_list_id" required defaultValue="">
            <option value="" disabled>Select smart list</option>
            {lists.map(item => <option value={item.id} key={item.id}>{item.name} · {item.audience_count} leads</option>)}
          </select>
          <select name="template_id" required defaultValue="">
            <option value="" disabled>Select message template</option>
            {templates.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select>
          <div className={styles.guardrail}><b>Execution boundary</b><br/>Creating a campaign never sends SMS. Prepare renders personalization and applies content, suppression and frequency preflight. Recipient-level compliance and owner approval remain mandatory before Bland dispatch.</div>
          <button disabled={loading || !lists.length || !templates.length}>Create campaign</button>
        </form>
      </article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span className={styles.eyebrow}>CAMPAIGN CONTROL</span><h2>SAHJONY seller campaigns</h2></div><small>{campaigns.length} campaigns</small></div>
      <div className={styles.tableWrap}><table>
        <thead><tr><th>Campaign</th><th>Status</th><th>Audience</th><th>Prepared</th><th>Suppressed</th><th>Compliance queue</th><th>Action</th></tr></thead>
        <tbody>
          {campaigns.map(item => <tr key={item.id}>
            <td><b>{item.name}</b><small>#{item.id} · {new Date(item.created_at).toLocaleString()}</small></td>
            <td><span className={styles.badge}>{item.status}</span></td>
            <td>{item.audience_count}</td><td>{item.prepared_count}</td><td>{item.suppressed_count}</td><td>{item.ready_count}</td>
            <td><button className={styles.smallButton} onClick={() => void prepareCampaign(item.id)} disabled={loading || ['active','completed'].includes(item.status)}>Prepare + preflight</button></td>
          </tr>)}
          {!campaigns.length && <tr><td colSpan={7} className={styles.empty}>Create a smart list and template to build the first SAHJONY campaign.</td></tr>}
        </tbody>
      </table></div>
    </section>
  </main>;
}
