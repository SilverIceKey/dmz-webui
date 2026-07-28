import { useEffect, useState } from 'react';
import { services, ports, system } from '../utils/api';
import type { ServiceStatus, PortProcess, SystemMetrics } from '../types';
import NavbarBrand from '../components/NavbarBrand';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

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

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatBitrate(bytesPerSec: number) {
  if (bytesPerSec === 0) return '0 B/s';
  const k = 1024;
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  const i = Math.floor(Math.log(bytesPerSec) / Math.log(k));
  return parseFloat((bytesPerSec / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatUptime(seconds: number) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d > 0) parts.push(`${d}天`);
  if (h > 0) parts.push(`${h}小时`);
  if (m > 0) parts.push(`${m}分钟`);
  return parts.join(' ') || '小于1分钟';
}

function getStatusColor(percent: number) {
  if (percent >= 85) return '#e74c3c';
  if (percent >= 70) return '#f39c12';
  return '#2ecc71';
}

interface MetricCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  percent?: number;
  color?: string;
}

function MetricCard({ title, value, subtext, percent, color }: MetricCardProps) {
  const barColor = color || (percent !== undefined ? getStatusColor(percent) : '#3498db');
  return (
    <div className="metric-card">
      <h3>{title}</h3>
      <div className="metric-value" style={{ color: barColor }}>{value}</div>
      {subtext && <div className="metric-subtext">{subtext}</div>}
      {percent !== undefined && (
        <div className="progress-bar">
          <div
            className="progress-fill"
            style={{ width: `${Math.min(100, percent)}%`, background: barColor }}
          />
        </div>
      )}
    </div>
  );
}

function SkeletonMetricCard() {
  return (
    <div className="metric-card skeleton-card">
      <div className="skeleton-line skeleton-title" />
      <div className="skeleton-line skeleton-value" />
      <div className="skeleton-line skeleton-subtext" />
      <div className="progress-bar">
        <div className="progress-fill skeleton-fill" style={{ width: '60%' }} />
      </div>
    </div>
  );
}

function SkeletonTableRow() {
  return (
    <tr>
      <td><span className="skeleton-inline" /></td>
      <td><span className="skeleton-inline" /></td>
      <td><span className="skeleton-inline" /></td>
      <td><span className="skeleton-inline" /></td>
    </tr>
  );
}

export default function Dashboard() {
  const [svcList, setSvcList] = useState<ServiceStatus[]>([]);
  const [portList, setPortList] = useState<PortProcess[]>([]);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [history, setHistory] = useState<{ time: string; cpu: number; netIn: number; netOut: number }[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);

  const fetchData = async () => {
    try {
      const [svcRes, portRes, metricsRes] = await Promise.all([
        services.status(),
        ports.processes(),
        system.metrics(),
      ]);
      setSvcList(svcRes.data);
      setPortList(portRes.data);
      const m = metricsRes.data as SystemMetrics;
      setMetrics(m);

      const now = new Date();
      const timeLabel = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
      setHistory((prev) => {
        const next = [...prev, {
          time: timeLabel,
          cpu: m.cpu_percent,
          netIn: m.network.recv_rate,
          netOut: m.network.sent_rate,
        }];
        return next.slice(-60);
      });
    } catch (e) {
      console.error(e);
    } finally {
      setInitialLoading(false);
    }
  };

  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const init = async () => {
      try {
        const res = await system.history();
        const records = res.data as Array<{
          server_time: number;
          cpu_percent: number;
          network: { recv_rate: number; sent_rate: number };
        }>;
        const restored = records.map((r) => {
          const d = new Date(r.server_time * 1000);
          return {
            time: `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`,
            cpu: r.cpu_percent,
            netIn: r.network.recv_rate,
            netOut: r.network.sent_rate,
          };
        });
        setHistory(restored);
      } catch (e) {
        console.error('加载历史监控数据失败', e);
      } finally {
        fetchData();
        intervalId = setInterval(fetchData, 5000);
      }
    };

    init();

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, []);

  const handleApply = async (svc: string) => {
    const action = svc === 'nftables'
      ? '重新应用 DMZ WebUI 管理的防火墙规则'
      : `重载 ${svc}`;
    if (!confirm(`确定要${action}吗？`)) return;
    try {
      await services.apply(svc);
      alert('重载成功');
      fetchData();
    } catch (e: any) {
      alert('重载失败: ' + (e.response?.data?.detail || e.message));
    }
  };

  return (
    <div>
      <Navbar />
      <div className="container">
        {/* 服务状态 */}
        <div className="status-cards">
          {svcList.map((s) => (
            <div className="status-card" key={s.name}>
              <h3>{s.name.toUpperCase()}</h3>
              <div className="value" style={{ color: s.active ? '#2ecc71' : '#e74c3c' }}>
                {s.active ? '运行中' : '已停止'}
              </div>
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-warning" onClick={() => handleApply(s.name)}>
                  {s.name === 'nftables' ? '应用项目规则' : '重载'}
                </button>
              </div>
            </div>
          ))}
          <div className="status-card">
            <h3>监听端口数</h3>
            <div className="value">{portList.length}</div>
          </div>
        </div>

        {/* 系统资源仪表盘 */}
        <div className="dashboard-section">
          <h2 className="section-title">系统资源监控</h2>
          <div className="dashboard-grid">
            {initialLoading && !metrics ? (
              <>
                <SkeletonMetricCard />
                <SkeletonMetricCard />
                <SkeletonMetricCard />
                <SkeletonMetricCard />
              </>
            ) : metrics ? (
              <>
                <MetricCard
                  title="CPU 使用率"
                  value={`${metrics.cpu_percent}%`}
                  percent={metrics.cpu_percent}
                  subtext={`负载: ${metrics.load_average.map((v) => v.toFixed(2)).join(' / ')}`}
                />
                <MetricCard
                  title="内存使用率"
                  value={`${metrics.memory.percent}%`}
                  percent={metrics.memory.percent}
                  subtext={`已用 ${metrics.memory.used_gb} GB / 共 ${metrics.memory.total_gb} GB`}
                />
                <MetricCard
                  title="磁盘使用率"
                  value={`${metrics.disk.percent}%`}
                  percent={metrics.disk.percent}
                  subtext={`已用 ${metrics.disk.used_gb} GB / 共 ${metrics.disk.total_gb} GB`}
                />
                <MetricCard
                  title="网络速率"
                  value={`↑ ${formatBitrate(metrics.network.sent_rate)}`}
                  subtext={`↓ ${formatBitrate(metrics.network.recv_rate)}`}
                  color="#3498db"
                />
              </>
            ) : null}
          </div>
        </div>

        {/* 趋势图 */}
        <div className="dashboard-section">
          <h2 className="section-title">实时趋势</h2>
          <div className="charts-grid">
            <div className="chart-card">
              <h3>CPU 使用率 (%)</h3>
              <div className="chart-wrap">
                {history.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                      <XAxis dataKey="time" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="cpu"
                        stroke="#3498db"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-placeholder">正在收集数据...</div>
                )}
              </div>
            </div>
            <div className="chart-card">
              <h3>网络速率</h3>
              <div className="chart-wrap">
                {history.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                      <XAxis dataKey="time" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip formatter={(value: number) => formatBitrate(value)} />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="netIn"
                        name="下载"
                        stroke="#2ecc71"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="netOut"
                        name="上传"
                        stroke="#e74c3c"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-placeholder">正在收集数据...</div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 系统信息 + 端口 TOP 10 */}
        <div className="dashboard-section">
          <h2 className="section-title">系统信息 & 端口占用</h2>
          <div className="info-grid">
            <div className="card system-info-card">
              <h3>服务器信息</h3>
              {initialLoading && !metrics ? (
                <div className="info-list">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div className="info-row" key={i}>
                      <span className="skeleton-inline" />
                      <span className="skeleton-inline skeleton-short" />
                    </div>
                  ))}
                </div>
              ) : metrics ? (
                <div className="info-list">
                  <div className="info-row">
                    <span>运行时间</span>
                    <strong>{formatUptime(metrics.uptime_seconds)}</strong>
                  </div>
                  <div className="info-row">
                    <span>启动时间</span>
                    <strong>{new Date(metrics.boot_time * 1000).toLocaleString()}</strong>
                  </div>
                  <div className="info-row">
                    <span>总发送流量</span>
                    <strong>{formatBytes(metrics.network.bytes_sent)}</strong>
                  </div>
                  <div className="info-row">
                    <span>总接收流量</span>
                    <strong>{formatBytes(metrics.network.bytes_recv)}</strong>
                  </div>
                  <div className="info-row">
                    <span>1 / 5 / 15 分钟负载</span>
                    <strong>{metrics.load_average.map((v) => v.toFixed(2)).join(' / ')}</strong>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="card port-table-card">
              <h3>监听端口进程 TOP 10</h3>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>协议</th>
                      <th>端口</th>
                      <th>PID</th>
                      <th>进程</th>
                    </tr>
                  </thead>
                  <tbody>
                    {initialLoading ? (
                      <>
                        <SkeletonTableRow />
                        <SkeletonTableRow />
                        <SkeletonTableRow />
                        <SkeletonTableRow />
                        <SkeletonTableRow />
                      </>
                    ) : (
                      [...portList]
                        .sort((a, b) => a.port - b.port)
                        .slice(0, 10)
                        .map((p) => (
                          <tr key={`${p.protocol}-${p.port}`}>
                            <td>{p.protocol.toUpperCase()}</td>
                            <td>{p.port}</td>
                            <td>{p.pid ?? '-'}</td>
                            <td>{p.command ?? '-'}</td>
                          </tr>
                        ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
