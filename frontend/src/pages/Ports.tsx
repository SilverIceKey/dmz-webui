import { useEffect, useState } from 'react';
import { ports } from '../utils/api';
import type { PortProcess } from '../types';
import NavbarBrand from '../components/NavbarBrand';

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
        <a href="/admin/ports">端口占用</a>
        <a href="#" onClick={logout}>退出</a>
      </div>
    </nav>
  );
}

export default function PortsPage() {
  const [list, setList] = useState<PortProcess[]>([]);
  const [search, setSearch] = useState('');

  const fetchData = async () => {
    try {
      const res = await ports.processes();
      setList(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => clearInterval(id);
  }, []);

  const filtered = list.filter((p) =>
    String(p.port).includes(search) ||
    (p.command || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <Navbar />
      <div className="container">
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>端口进程占用</h2>
            <input
              placeholder="搜索端口或进程名"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 240 }}
            />
          </div>
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
              {filtered.map((p, idx) => (
                <tr key={idx}>
                  <td>{p.protocol.toUpperCase()}</td>
                  <td>{p.port}</td>
                  <td>{p.pid}</td>
                  <td>{p.command}</td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={4} style={{ textAlign: 'center', color: '#718093' }}>无数据</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
