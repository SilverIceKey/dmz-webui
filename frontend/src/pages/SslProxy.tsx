import { useEffect, useState } from 'react';
import { sslProxy } from '../utils/api';
import type { SslProxyRule } from '../types';

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

export default function SslProxyPage() {
  const [rules, setRules] = useState<SslProxyRule[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<SslProxyRule | null>(null);

  const fetchRules = async () => {
    try {
      const res = await sslProxy.list();
      setRules(res.data);
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

  return (
    <div>
      <Navbar />
      <div className="container">
        <div className="page-header">
          <h1>SSL 代理转发</h1>
          <div className="page-actions">
            <button className="btn btn-primary" onClick={openAdd}>+ 添加规则</button>
          </div>
        </div>

        <div className="info-banner">
          启用 SSL 时，Caddy 会监听指定端口并提供 <code>https://&lt;your-domain&gt;:端口</code>；
          不启用 SSL 时，仅通过 nftables 做普通端口转发。
        </div>

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
      </div>

      <RuleModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); setEditingRule(null); }}
        onSave={handleSave}
        initial={editingRule}
      />
    </div>
  );
}
