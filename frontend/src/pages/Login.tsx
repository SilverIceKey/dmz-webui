import { useState } from 'react';
import { auth } from '../utils/api';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await auth.login(username, password);
      localStorage.setItem('token', res.data.token);
      window.location.href = '/admin';
    } catch (err: any) {
      setError(err.response?.data?.detail || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>DMZ WebUI</h1>
        <p style={{ textAlign: 'center', color: '#718093', marginBottom: 20, fontSize: 13 }}>
          使用 Linux 系统账户登录
        </p>
        {error && (
          <div style={{ background: '#f8d7da', color: '#721c24', padding: 10, borderRadius: 6, marginBottom: 14, fontSize: 13 }}>
            {error}
          </div>
        )}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>用户名</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="form-group">
            <label>密码</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  );
}
