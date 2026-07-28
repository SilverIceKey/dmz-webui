import { useEffect, useState } from 'react';
import { nftables } from '../utils/api';
import type { LocalPortRule, NfRule } from '../types';
import NavbarBrand from '../components/NavbarBrand';
import { formatApiError } from '../utils/errors';

function Navbar() {
  const logout = () => {
    localStorage.removeItem('token');
    window.location.href = '/admin/login';
  };
  return (
    <nav className="navbar">
      <NavbarBrand />
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
  rule_type: 'forward' | 'local';
  protocol: string;
  port: string;
  dest_ip: string;
  dest_port: string;
  comment: string;
  whitelist_type: string;
  whitelist_ips: string;
}

const emptyForm: RuleFormData = {
  rule_type: 'forward',
  protocol: 'both',
  port: '',
  dest_ip: '',
  dest_port: '',
  comment: '',
  whitelist_type: 'all',
  whitelist_ips: '',
};

type FirewallRule =
  | (NfRule & { rule_type: 'forward' })
  | (LocalPortRule & { rule_type: 'local' });

function RuleModal({
  open,
  onClose,
  onSave,
  initial,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (data: RuleFormData) => void;
  initial: FirewallRule | null;
}) {
  const [form, setForm] = useState<RuleFormData>(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      setForm({
        rule_type: initial.rule_type,
        protocol: initial.protocol,
        port: String(initial.port),
        dest_ip: initial.rule_type === 'forward' ? initial.dest_ip : '',
        dest_port: initial.rule_type === 'forward' ? String(initial.dest_port) : '',
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
            <label>规则类型</label>
            <select
              value={form.rule_type}
              disabled={isEdit}
              onChange={(e) => setForm({
                ...form,
                rule_type: e.target.value as RuleFormData['rule_type'],
              })}
            >
              <option value="forward">端口转发</option>
              <option value="local">本机端口开放</option>
            </select>
          </div>
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
          {form.rule_type === 'forward' && (
            <>
              <div className="form-group">
                <label>目标 IP</label>
                <input value={form.dest_ip} onChange={(e) => setForm({ ...form, dest_ip: e.target.value })} placeholder="192.168.x.x" required />
              </div>
              <div className="form-group">
                <label>目标端口</label>
                <input type="number" value={form.dest_port} onChange={(e) => setForm({ ...form, dest_port: e.target.value })} required />
              </div>
            </>
          )}
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
  const [rules, setRules] = useState<FirewallRule[]>([]);
  const [typeFilter, setTypeFilter] = useState('all');
  const [filter, setFilter] = useState('all');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<FirewallRule | null>(null);
  const [updatingCn, setUpdatingCn] = useState(false);

  const fetchRules = async () => {
    try {
      const [forwardResponse, localResponse] = await Promise.all([
        nftables.list(),
        nftables.listOpenPorts(),
      ]);
      setRules([
        ...forwardResponse.data.map((rule: NfRule) => ({
          ...rule,
          rule_type: 'forward' as const,
        })),
        ...localResponse.data.map((rule: LocalPortRule) => ({
          ...rule,
          rule_type: 'local' as const,
        })),
      ]);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const filteredRules = rules.filter(
    (rule) =>
      (typeFilter === 'all' || rule.rule_type === typeFilter)
      && (filter === 'all' || rule.protocol === filter)
  );

  const handleSave = async (form: RuleFormData) => {
    const commonData = {
      port: parseInt(form.port),
      protocol: form.protocol,
      comment: form.comment,
      whitelist_type: form.whitelist_type,
      whitelist_ips: form.whitelist_ips,
    };

    try {
      if (form.rule_type === 'local') {
        if (editingRule?.rule_type === 'local') {
          await nftables.editOpenPort(
            editingRule.protocol,
            editingRule.port,
            commonData
          );
        } else {
          await nftables.createOpenPort(commonData);
        }
      } else {
        const forwardData = {
          ...commonData,
          dest_ip: form.dest_ip,
          dest_port: parseInt(form.dest_port),
        };
        if (editingRule?.rule_type === 'forward') {
          await nftables.edit(
            editingRule.protocol,
            editingRule.port,
            editingRule.dest_ip,
            editingRule.dest_port,
            forwardData
          );
        } else {
          await nftables.create(forwardData);
        }
      }
      setModalOpen(false);
      setEditingRule(null);
      fetchRules();
    } catch (e: unknown) {
      alert('保存失败: ' + formatApiError(e));
    }
  };

  const handleDelete = async (rule: FirewallRule) => {
    const protoDisplay = rule.protocol === 'both' ? 'TCP/UDP' : rule.protocol.toUpperCase();
    const description = rule.rule_type === 'forward'
      ? `${protoDisplay}:${rule.port} → ${rule.dest_ip}:${rule.dest_port} 的端口转发`
      : `${protoDisplay}:${rule.port} 的本机开放`;
    if (!confirm(`确定删除 ${description} 规则？`)) return;
    try {
      if (rule.rule_type === 'forward') {
        await nftables.remove(
          rule.protocol,
          rule.port,
          rule.dest_ip,
          rule.dest_port
        );
      } else {
        await nftables.removeOpenPort(rule.protocol, rule.port);
      }
      fetchRules();
    } catch (e: unknown) {
      alert('删除失败: ' + formatApiError(e));
    }
  };

  const openAdd = () => {
    setEditingRule(null);
    setModalOpen(true);
  };

  const openEdit = (rule: FirewallRule) => {
    setEditingRule(rule);
    setModalOpen(true);
  };

  const handleUpdateCn = async () => {
    if (!confirm('确定从 APNIC 下载最新中国大陆 IP 列表？\n这会覆盖现有的大陆 IP 白名单数据。')) return;
    setUpdatingCn(true);
    try {
      await nftables.updateCnIpset();
      alert('大陆 IP 列表更新成功');
    } catch (e: unknown) {
      alert('更新失败: ' + formatApiError(e));
    } finally {
      setUpdatingCn(false);
    }
  };

  return (
    <div>
      <Navbar />
      <div className="container">
        <div className="page-header">
          <h1>防火墙规则</h1>
          <div className="page-actions">
            <button className="btn btn-secondary" onClick={handleUpdateCn} disabled={updatingCn}>
              {updatingCn ? '更新中...' : '更新大陆 IP'}
            </button>
            <button className="btn btn-primary" onClick={openAdd}>+ 添加规则</button>
          </div>
        </div>

        <div className="info-banner">
          端口转发用于将流量 DNAT 到其他地址；本机端口开放用于允许外部访问
          监听在本机网卡上的服务。两种类型均支持大陆、境外和自定义来源白名单。
        </div>

        <div className="filter-bar">
          {[
            { value: 'all', label: '全部类型' },
            { value: 'forward', label: '端口转发' },
            { value: 'local', label: '本机开放' },
          ].map((option) => (
            <button
              key={option.value}
              className={`filter-pill ${typeFilter === option.value ? 'active' : ''}`}
              onClick={() => setTypeFilter(option.value)}
            >
              {option.label}
            </button>
          ))}
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
            <div
              className="card rule-card"
              key={
                r.rule_type === 'forward'
                  ? `forward-${r.protocol}-${r.port}-${r.dest_ip}-${r.dest_port}`
                  : `local-${r.protocol}-${r.port}`
              }
            >
              <div className="rule-card-header">
                <span className={`protocol-badge ${r.protocol}`}>
                  {r.protocol === 'both' ? 'TCP/UDP' : r.protocol.toUpperCase()}
                </span>
                <span className="port-number">:{r.port}</span>
                <span className="rule-label">
                  {r.rule_type === 'forward' ? '端口转发' : '本机开放'}
                </span>
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
                  <span className="rule-value">
                    {r.rule_type === 'forward'
                      ? `${r.dest_ip}:${r.dest_port}`
                      : '本机监听服务'}
                  </span>
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
