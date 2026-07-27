import { useEffect, useState } from 'react';
import { nftables } from '../utils/api';
import type { NfRule } from '../types';

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

const PROTO_OPTIONS = [
  { value: 'all', label: '全部协议' },
  { value: 'tcp', label: 'TCP' },
  { value: 'udp', label: 'UDP' },
  { value: 'both', label: 'TCP/UDP' },
];

const WL_LABELS: Record<string, string> = {
  all: '全部',
  cn: '大陆 IP',
  abroad: '境外 IP',
  custom: '自定义',
};

interface RuleFormData {
  protocol: string;
  port: string;
  dest_ip: string;
  dest_port: string;
  comment: string;
  whitelist_type: string;
  whitelist_ips: string;
}

const emptyForm: RuleFormData = {
  protocol: 'both',
  port: '',
  dest_ip: '',
  dest_port: '',
  comment: '',
  whitelist_type: 'all',
  whitelist_ips: '',
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
  initial: NfRule | null;
}) {
  const [form, setForm] = useState<RuleFormData>(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      setForm({
        protocol: initial.protocol,
        port: String(initial.port),
        dest_ip: initial.dest_ip,
        dest_port: String(initial.dest_port),
        comment: initial.comment || '',
        whitelist_type: initial.whitelist_type,
        whitelist_ips: initial.whitelist_ips || '',
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
            <label>协议</label>
            <select value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
              <option value="both">TCP/UDP</option>
            </select>
          </div>
          <div className="form-group">
            <label>外部端口</label>
            <input type="number" value={form.port} disabled={isEdit} onChange={(e) => setForm({ ...form, port: e.target.value })} required />
          </div>
          <div className="form-group">
            <label>目标 IP</label>
            <input value={form.dest_ip} onChange={(e) => setForm({ ...form, dest_ip: e.target.value })} placeholder="192.168.x.x" required />
          </div>
          <div className="form-group">
            <label>目标端口</label>
            <input type="number" value={form.dest_port} onChange={(e) => setForm({ ...form, dest_port: e.target.value })} required />
          </div>
          <div className="form-group">
            <label>白名单</label>
            <select value={form.whitelist_type} onChange={(e) => setForm({ ...form, whitelist_type: e.target.value })}>
              <option value="all">全部（无限制）</option>
              <option value="cn">大陆 IP</option>
              <option value="abroad">境外 IP</option>
              <option value="custom">自定义 IP</option>
            </select>
          </div>
          {form.whitelist_type === 'custom' && (
            <div className="form-group">
              <label>自定义 IP / CIDR（逗号分隔）</label>
              <input
                value={form.whitelist_ips}
                onChange={(e) => setForm({ ...form, whitelist_ips: e.target.value })}
                placeholder="192.168.1.100, 10.0.0.0/8"
                required
              />
            </div>
          )}
          <div className="form-group">
            <label>备注</label>
            <input value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
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

export default function NftablesPage() {
  const [rules, setRules] = useState<NfRule[]>([]);
  const [filter, setFilter] = useState('all');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<NfRule | null>(null);
  const [updatingCn, setUpdatingCn] = useState(false);

  const fetchRules = async () => {
    try {
      const res = await nftables.list();
      setRules(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const filteredRules = rules.filter((r) => filter === 'all' || r.protocol === filter);

  const handleSave = async (form: RuleFormData) => {
    const data = {
      port: parseInt(form.port),
      protocol: form.protocol,
      dest_ip: form.dest_ip,
      dest_port: parseInt(form.dest_port),
      comment: form.comment,
      whitelist_type: form.whitelist_type,
      whitelist_ips: form.whitelist_ips,
    };

    try {
      if (editingRule) {
        await nftables.edit(
          editingRule.protocol,
          editingRule.port,
          editingRule.dest_ip,
          editingRule.dest_port,
          data
        );
      } else {
        await nftables.create(data);
      }
      setModalOpen(false);
      setEditingRule(null);
      fetchRules();
    } catch (e: any) {
      alert('保存失败: ' + (e.response?.data?.detail || e.message));
    }
  };

  const handleDelete = async (rule: NfRule) => {
    const protoDisplay = rule.protocol === 'both' ? 'TCP/UDP' : rule.protocol.toUpperCase();
    if (!confirm(`确定删除 ${protoDisplay}:${rule.port} → ${rule.dest_ip}:${rule.dest_port} 的规则？`)) return;
    try {
      await nftables.remove(rule.protocol, rule.port, rule.dest_ip, rule.dest_port);
      fetchRules();
    } catch (e: any) {
      alert('删除失败: ' + (e.response?.data?.detail || e.message));
    }
  };

  const openAdd = () => {
    setEditingRule(null);
    setModalOpen(true);
  };

  const openEdit = (rule: NfRule) => {
    setEditingRule(rule);
    setModalOpen(true);
  };

  const handleUpdateCn = async () => {
    if (!confirm('确定从 APNIC 下载最新中国大陆 IP 列表？\n这会覆盖现有的大陆 IP 白名单数据。')) return;
    setUpdatingCn(true);
    try {
      await nftables.updateCnIpset();
      alert('大陆 IP 列表更新成功');
    } catch (e: any) {
      alert('更新失败: ' + (e.response?.data?.detail || e.message));
    } finally {
      setUpdatingCn(false);
    }
  };

  return (
    <div>
      <Navbar />
      <div className="container">
        <div className="page-header">
          <h1>防火墙端口转发</h1>
          <div className="page-actions">
            <button className="btn btn-secondary" onClick={handleUpdateCn} disabled={updatingCn}>
              {updatingCn ? '更新中...' : '更新大陆 IP'}
            </button>
            <button className="btn btn-primary" onClick={openAdd}>+ 添加规则</button>
          </div>
        </div>

        <div className="filter-bar">
          {PROTO_OPTIONS.map((o) => (
            <button
              key={o.value}
              className={`filter-pill ${filter === o.value ? 'active' : ''}`}
              onClick={() => setFilter(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>

        <div className="cards-grid">
          {filteredRules.map((r) => (
            <div className="card rule-card" key={`${r.protocol}-${r.port}-${r.dest_ip}-${r.dest_port}`}>
              <div className="rule-card-header">
                <span className={`protocol-badge ${r.protocol}`}>
                  {r.protocol === 'both' ? 'TCP/UDP' : r.protocol.toUpperCase()}
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
                <div className="rule-row">
                  <span className="rule-label">白名单</span>
                  <span className="rule-value">
                    {WL_LABELS[r.whitelist_type] || r.whitelist_type}
                    {r.whitelist_type === 'custom' && r.whitelist_ips ? (
                      <div className="rule-ips">{r.whitelist_ips}</div>
                    ) : null}
                  </span>
                </div>
              </div>
              <div className="rule-card-actions">
                <button className="btn btn-sm btn-secondary" onClick={() => openEdit(r)}>编辑</button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r)}>删除</button>
              </div>
            </div>
          ))}
          {filteredRules.length === 0 && (
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
