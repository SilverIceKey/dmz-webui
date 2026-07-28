import { useEffect, useState } from 'react';
import { siteRoutes, sslProxy } from '../utils/api';
import type { SiteRoute, SslProxyRule } from '../types';

function Navbar() {
  const logout = () => {
    localStorage.removeItem('token');
    window.location.href = '/admin/login';
  };
  return (
    <nav className="navbar">
      <div className="navbar-brand">DMZ WebUI</div>
      <div className="navbar-links">
        <a href="/admin">概览</a>
        <a href="/admin/nftables">防火墙</a>
        <a href="/admin/ssl-proxy">SSL 代理</a>
        <a href="/admin/ports">端口占用</a>
        <a href="#" onClick={logout}>退出</a>
      </div>
    </nav>
  );
}

interface RuleFormData {
  port: string;
  dest_ip: string;
  dest_port: string;
  ssl_enabled: boolean;
  comment: string;
}

const emptyForm: RuleFormData = {
  port: '',
  dest_ip: '',
  dest_port: '',
  ssl_enabled: true,
  comment: '',
};

function RuleModal({
  open,
  onClose,
  onSave,
  initial,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (data: RuleFormData) => void;
  initial: SslProxyRule | null;
}) {
  const [form, setForm] = useState<RuleFormData>(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      setForm({
        port: String(initial.port),
        dest_ip: initial.dest_ip,
        dest_port: String(initial.dest_port),
        ssl_enabled: initial.ssl_enabled,
        comment: initial.comment || '',
      });
    } else {
      setForm(emptyForm);
    }
  }, [initial, open]);

  if (!open) return null;

  const isEdit = !!initial;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({ ...form });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{isEdit ? '编辑规则' : '添加规则'}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>外部端口</label>
            <input
              type="number"
              value={form.port}
              disabled={isEdit}
              onChange={(e) => setForm({ ...form, port: e.target.value })}
              placeholder="例如 8444"
              required
            />
          </div>
          <div className="form-group">
            <label>目标 IP</label>
            <input
              value={form.dest_ip}
              onChange={(e) => setForm({ ...form, dest_ip: e.target.value })}
              placeholder="192.168.x.x"
              required
            />
          </div>
          <div className="form-group">
            <label>目标端口</label>
            <input
              type="number"
              value={form.dest_port}
              onChange={(e) => setForm({ ...form, dest_port: e.target.value })}
              required
            />
          </div>
          <div className="form-group form-checkbox">
            <label>
              <input
                type="checkbox"
                checked={form.ssl_enabled}
                onChange={(e) => setForm({ ...form, ssl_enabled: e.target.checked })}
              />
              启用 SSL（通过 Caddy 提供 https://&lt;your-domain&gt;:端口）
            </label>
          </div>
          <div className="form-group">
            <label>备注</label>
            <input
              value={form.comment}
              onChange={(e) => setForm({ ...form, comment: e.target.value })}
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface SiteRouteFormData {
  route_type: 'proxy' | 'static';
  hostname: string;
  path: string;
  dest_host: string;
  dest_port: string;
  strip_prefix: boolean;
  ssl_enabled: boolean;
  comment: string;
}

const emptySiteRouteForm: SiteRouteFormData = {
  route_type: 'proxy',
  hostname: '',
  path: '/',
  dest_host: '127.0.0.1',
  dest_port: '',
  strip_prefix: true,
  ssl_enabled: true,
  comment: '',
};

function SiteRouteModal({
  open,
  onClose,
  onSave,
  initial,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (data: SiteRouteFormData) => Promise<void>;
  initial: SiteRoute | null;
}) {
  const [form, setForm] = useState<SiteRouteFormData>(emptySiteRouteForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      setForm({
        route_type: initial.route_type,
        hostname: initial.hostname,
        path: initial.path,
        dest_host: initial.dest_host || '127.0.0.1',
        dest_port: initial.dest_port ? String(initial.dest_port) : '',
        strip_prefix: initial.strip_prefix,
        ssl_enabled: initial.ssl_enabled,
        comment: initial.comment || '',
      });
    } else {
      setForm(emptySiteRouteForm);
    }
  }, [initial, open]);

  if (!open) return null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave(form);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{initial ? '编辑站点路由' : '添加站点路由'}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>路由类型</label>
            <select
              value={form.route_type}
              onChange={(event) => setForm({
                ...form,
                route_type: event.target.value as SiteRouteFormData['route_type'],
              })}
            >
              <option value="proxy">反向代理</option>
              <option value="static">静态文件</option>
            </select>
          </div>
          <div className="form-group">
            <label>访问域名</label>
            <input
              value={form.hostname}
              onChange={(event) => setForm({ ...form, hostname: event.target.value })}
              placeholder="headscale.example.com"
              required
            />
          </div>
          <div className="form-group">
            <label>访问路径</label>
            <input
              value={form.path}
              onChange={(event) => setForm({ ...form, path: event.target.value })}
              placeholder={form.route_type === 'static' ? '/derper.json' : '/'}
              required
            />
          </div>
          {form.route_type === 'proxy' && (
            <>
              <div className="form-group">
                <label>目标主机</label>
                <input
                  value={form.dest_host}
                  onChange={(event) => setForm({ ...form, dest_host: event.target.value })}
                  placeholder="127.0.0.1"
                  required
                />
              </div>
              <div className="form-group">
                <label>目标端口</label>
                <input
                  type="number"
                  value={form.dest_port}
                  onChange={(event) => setForm({ ...form, dest_port: event.target.value })}
                  required
                />
              </div>
              {form.path !== '/' && (
                <div className="form-group form-checkbox">
                  <label>
                    <input
                      type="checkbox"
                      checked={form.strip_prefix}
                      onChange={(event) => setForm({
                        ...form,
                        strip_prefix: event.target.checked,
                      })}
                    />
                    转发前去掉访问路径前缀
                  </label>
                </div>
              )}
            </>
          )}
          <div className="form-group form-checkbox">
            <label>
              <input
                type="checkbox"
                checked={form.ssl_enabled}
                onChange={(event) => setForm({
                  ...form,
                  ssl_enabled: event.target.checked,
                })}
              />
              启用 SSL（二级域名由 Caddy 自动申请并续签证书）
            </label>
          </div>
          <div className="form-group">
            <label>备注</label>
            <input
              value={form.comment}
              onChange={(event) => setForm({ ...form, comment: event.target.value })}
            />
          </div>
          {form.route_type === 'static' && (
            <div className="info-banner">
              保存后页面会显示服务器存放目录。将与访问路径同名的文件放入该目录即可。
            </div>
          )}
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function SslProxyPage() {
  const [rules, setRules] = useState<SslProxyRule[]>([]);
  const [siteRouteRules, setSiteRouteRules] = useState<SiteRoute[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<SslProxyRule | null>(null);
  const [siteModalOpen, setSiteModalOpen] = useState(false);
  const [editingSiteRoute, setEditingSiteRoute] = useState<SiteRoute | null>(null);

  const fetchRules = async () => {
    try {
      const [portResponse, siteResponse] = await Promise.all([
        sslProxy.list(),
        siteRoutes.list(),
      ]);
      setRules(portResponse.data);
      setSiteRouteRules(siteResponse.data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const handleSave = async (form: RuleFormData) => {
    const data = {
      port: parseInt(form.port),
      dest_ip: form.dest_ip,
      dest_port: parseInt(form.dest_port),
      ssl_enabled: form.ssl_enabled,
      comment: form.comment,
    };

    try {
      if (editingRule) {
        await sslProxy.update(editingRule.id, data);
      } else {
        await sslProxy.create(data);
      }
      setModalOpen(false);
      setEditingRule(null);
      fetchRules();
    } catch (e: any) {
      alert('保存失败: ' + (e.response?.data?.detail || e.message));
    }
  };

  const handleDelete = async (rule: SslProxyRule) => {
    const mode = rule.ssl_enabled ? 'SSL 代理' : '普通端口转发';
    if (!confirm(`确定删除 ${mode} ${rule.port} → ${rule.dest_ip}:${rule.dest_port} 的规则？`)) return;
    try {
      await sslProxy.remove(rule.id);
      fetchRules();
    } catch (e: any) {
      alert('删除失败: ' + (e.response?.data?.detail || e.message));
    }
  };

  const openAdd = () => {
    setEditingRule(null);
    setModalOpen(true);
  };

  const openEdit = (rule: SslProxyRule) => {
    setEditingRule(rule);
    setModalOpen(true);
  };

  const handleSiteRouteSave = async (form: SiteRouteFormData) => {
    const data = {
      route_type: form.route_type,
      hostname: form.hostname,
      path: form.path,
      dest_host: form.route_type === 'proxy' ? form.dest_host : null,
      dest_port: form.route_type === 'proxy' ? parseInt(form.dest_port) : null,
      strip_prefix: form.route_type === 'proxy' && form.path !== '/'
        ? form.strip_prefix
        : false,
      ssl_enabled: form.ssl_enabled,
      comment: form.comment,
    };
    try {
      if (editingSiteRoute) {
        await siteRoutes.update(editingSiteRoute.id, data);
      } else {
        await siteRoutes.create(data);
      }
      setSiteModalOpen(false);
      setEditingSiteRoute(null);
      fetchRules();
    } catch (error: any) {
      alert('保存失败: ' + (error.response?.data?.detail || error.message));
    }
  };

  const handleSiteRouteDelete = async (rule: SiteRoute) => {
    if (!confirm(`确定删除 ${rule.hostname}${rule.path} 的站点路由？静态文件不会删除。`)) return;
    try {
      await siteRoutes.remove(rule.id);
      fetchRules();
    } catch (error: any) {
      alert('删除失败: ' + (error.response?.data?.detail || error.message));
    }
  };

  return (
    <div>
      <Navbar />
      <div className="container">
        <div className="page-header">
          <h1>SSL 代理转发</h1>
          <div className="page-actions">
            <button className="btn btn-secondary" onClick={openAdd}>+ 端口代理</button>
            <button
              className="btn btn-primary"
              onClick={() => {
                setEditingSiteRoute(null);
                setSiteModalOpen(true);
              }}
            >
              + 站点路由
            </button>
          </div>
        </div>

        <div className="info-banner">
          启用 SSL 时，Caddy 会监听指定端口并提供 <code>https://&lt;your-domain&gt;:端口</code>；
          不启用 SSL 时，仅通过 nftables 做普通端口转发。
        </div>

        <h2>端口代理</h2>
        <div className="cards-grid">
          {rules.map((r) => (
            <div className="card rule-card" key={r.id}>
              <div className="rule-card-header">
                <span className={`protocol-badge ${r.ssl_enabled ? 'tcp' : 'udp'}`}>
                  {r.ssl_enabled ? 'SSL' : '转发'}
                </span>
                <span className="port-number">:{r.port}</span>
              </div>
              <div className="rule-card-body">
                <div className="rule-row rule-comment-row">
                  <span className="rule-label">备注</span>
                  <span className={`rule-value rule-comment ${r.comment ? 'has-comment' : ''}`}>
                    {r.comment || '-'}
                  </span>
                </div>
                <div className="rule-row">
                  <span className="rule-label">目标</span>
                  <span className="rule-value">{r.dest_ip}:{r.dest_port}</span>
                </div>
                {r.ssl_enabled && (
                  <div className="rule-row">
                    <span className="rule-label">访问地址</span>
                    <a
                      className="rule-value"
                      href={`https://${window.location.hostname}:${r.port}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      https://{window.location.hostname}:{r.port}
                    </a>
                  </div>
                )}
              </div>
              <div className="rule-card-actions">
                <button className="btn btn-sm btn-secondary" onClick={() => openEdit(r)}>编辑</button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r)}>删除</button>
              </div>
            </div>
          ))}
          {rules.length === 0 && (
            <div className="empty-state">暂无规则</div>
          )}
        </div>

        <h2>域名与路径路由</h2>
        <div className="info-banner">
          二级域名启用 SSL 时由 Caddy 自动申请并续签证书，请先完成 DNS 解析。
          静态文件规则会显示服务器存放目录，不会自动删除目录中的文件。
        </div>
        <div className="cards-grid">
          {siteRouteRules.map((rule) => {
            const scheme = rule.ssl_enabled ? 'https' : 'http';
            const accessUrl = `${scheme}://${rule.hostname}${rule.path}`;
            return (
              <div className="card rule-card" key={rule.id}>
                <div className="rule-card-header">
                  <span className={`protocol-badge ${rule.route_type === 'proxy' ? 'tcp' : 'udp'}`}>
                    {rule.route_type === 'proxy' ? '反向代理' : '静态文件'}
                  </span>
                  <span className="rule-label">
                    {rule.ssl_enabled ? 'HTTPS' : 'HTTP'}
                  </span>
                </div>
                <div className="rule-card-body">
                  <div className="rule-row rule-comment-row">
                    <span className="rule-label">备注</span>
                    <span className={`rule-value rule-comment ${rule.comment ? 'has-comment' : ''}`}>
                      {rule.comment || '-'}
                    </span>
                  </div>
                  <div className="rule-row">
                    <span className="rule-label">访问地址</span>
                    <a
                      className="rule-value"
                      href={accessUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {accessUrl}
                    </a>
                  </div>
                  {rule.route_type === 'proxy' ? (
                    <div className="rule-row">
                      <span className="rule-label">目标</span>
                      <span className="rule-value">
                        {rule.dest_host}:{rule.dest_port}
                        {rule.path !== '/' && rule.strip_prefix ? '（去前缀）' : ''}
                      </span>
                    </div>
                  ) : (
                    <div className="rule-row">
                      <span className="rule-label">存放目录</span>
                      <code className="rule-value">{rule.static_directory}</code>
                    </div>
                  )}
                </div>
                <div className="rule-card-actions">
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => {
                      setEditingSiteRoute(rule);
                      setSiteModalOpen(true);
                    }}
                  >
                    编辑
                  </button>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleSiteRouteDelete(rule)}
                  >
                    删除
                  </button>
                </div>
              </div>
            );
          })}
          {siteRouteRules.length === 0 && (
            <div className="empty-state">暂无站点路由</div>
          )}
        </div>
      </div>

      <RuleModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); setEditingRule(null); }}
        onSave={handleSave}
        initial={editingRule}
      />
      <SiteRouteModal
        open={siteModalOpen}
        onClose={() => {
          setSiteModalOpen(false);
          setEditingSiteRoute(null);
        }}
        onSave={handleSiteRouteSave}
        initial={editingSiteRoute}
      />
    </div>
  );
}
