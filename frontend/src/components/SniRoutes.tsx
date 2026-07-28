import { useEffect, useState } from 'react';
import { usePublicConfig } from '../context/PublicConfigContext';
import type { SniRoute } from '../types';
import { sniRoutes } from '../utils/api';
import { formatApiError } from '../utils/errors';

interface SniRouteFormData {
  hostname: string;
  dest_host: string;
  dest_port: string;
  comment: string;
}

const emptyForm: SniRouteFormData = {
  hostname: '',
  dest_host: '127.0.0.1',
  dest_port: '',
  comment: '',
};

function SniRouteModal({
  open,
  initial,
  onClose,
  onSave,
}: {
  open: boolean;
  initial: SniRoute | null;
  onClose: () => void;
  onSave: (data: SniRouteFormData) => Promise<void>;
}) {
  const [form, setForm] = useState<SniRouteFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const { route_domain: routeDomain } = usePublicConfig();

  useEffect(() => {
    if (initial) {
      setForm({
        hostname: initial.hostname,
        dest_host: initial.dest_host,
        dest_port: String(initial.dest_port),
        comment: initial.comment || '',
      });
    } else {
      setForm(emptyForm);
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
          <h3>{initial ? '编辑 TCP/SNI 透传' : '添加 TCP/SNI 透传'}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>访问域名（TLS SNI）</label>
            <input
              value={form.hostname}
              onChange={(event) => setForm({ ...form, hostname: event.target.value })}
              placeholder="derper.example.com"
              required
            />
            {routeDomain && (
              <small>允许 {routeDomain} 及其子域名，不能与 HTTP 站点路由重复</small>
            )}
          </div>
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
              min="1"
              max="65535"
              value={form.dest_port}
              onChange={(event) => setForm({ ...form, dest_port: event.target.value })}
              placeholder="41103"
              required
            />
          </div>
          <div className="form-group">
            <label>备注</label>
            <input
              value={form.comment}
              onChange={(event) => setForm({ ...form, comment: event.target.value })}
              placeholder="DERP"
            />
          </div>
          <div className="info-banner">
            此类型原样透传 TLS/TCP，不由 Caddy 终止 TLS 或签发证书。
            目标服务必须自行提供与访问域名匹配的证书；UDP 端口需单独开放。
          </div>
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function SniRoutes() {
  const [rules, setRules] = useState<SniRoute[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SniRoute | null>(null);

  const fetchRules = async () => {
    try {
      const response = await sniRoutes.list();
      setRules(response.data);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const handleSave = async (form: SniRouteFormData) => {
    const data = {
      hostname: form.hostname,
      dest_host: form.dest_host,
      dest_port: parseInt(form.dest_port, 10),
      comment: form.comment,
    };
    try {
      if (editing) {
        await sniRoutes.update(editing.id, data);
      } else {
        await sniRoutes.create(data);
      }
      setModalOpen(false);
      setEditing(null);
      await fetchRules();
    } catch (error: unknown) {
      alert('保存失败: ' + formatApiError(error));
    }
  };

  const handleDelete = async (rule: SniRoute) => {
    if (!confirm(
      `确定删除 ${rule.hostname}:443 → ${rule.dest_host}:${rule.dest_port} 的 SNI 透传？`,
    )) return;
    try {
      await sniRoutes.remove(rule.id);
      await fetchRules();
    } catch (error: unknown) {
      alert('删除失败: ' + formatApiError(error));
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>TCP/SNI 透传</h2>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          + SNI 透传
        </button>
      </div>
      <div className="info-banner">
        标准 443 模式下按 TLS SNI 原样转发 TCP，适用于 DERP 等不能经过 HTTP
        反向代理的协议。目标服务负责 TLS 证书，UDP（如 DERP STUN 3478）
        不经过 Caddy。
      </div>
      <div className="cards-grid">
        {rules.map((rule) => (
          <div className="card rule-card" key={rule.id}>
            <div className="rule-card-header">
              <span className="protocol-badge tcp">TCP/SNI</span>
              <span className="port-number">:443</span>
            </div>
            <div className="rule-card-body">
              <div className="rule-row rule-comment-row">
                <span className="rule-label">备注</span>
                <span className={`rule-value rule-comment ${rule.comment ? 'has-comment' : ''}`}>
                  {rule.comment || '-'}
                </span>
              </div>
              <div className="rule-row">
                <span className="rule-label">SNI 域名</span>
                <span className="rule-value">{rule.hostname}</span>
              </div>
              <div className="rule-row">
                <span className="rule-label">目标</span>
                <span className="rule-value">
                  {rule.dest_host}:{rule.dest_port}
                </span>
              </div>
            </div>
            <div className="rule-card-actions">
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  setEditing(rule);
                  setModalOpen(true);
                }}
              >
                编辑
              </button>
              <button
                className="btn btn-sm btn-danger"
                onClick={() => handleDelete(rule)}
              >
                删除
              </button>
            </div>
          </div>
        ))}
        {rules.length === 0 && (
          <div className="empty-state">暂无 TCP/SNI 透传</div>
        )}
      </div>
      <SniRouteModal
        open={modalOpen}
        initial={editing}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSave={handleSave}
      />
    </>
  );
}
